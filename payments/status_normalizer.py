import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class NormalizedStatus:
    """
    The single status object PaySync produces from any provider response.

    Everything outside this module works with NormalizedStatus —
    never with raw M-Pesa codes directly.
    """
    status: str              # 'pending' | 'success' | 'failed'
    is_retryable: bool       # Should retry logic attempt again?
    is_permanent: bool       # Is this outcome final — no recovery possible?
    reason: str              # Human-readable explanation
    provider_code: Optional[int]    # Original provider code (for logging only)
    provider_message: Optional[str] # Original provider message (for logging only)


class MpesaStatusNormalizer:
    """
    Single source of truth for translating M-Pesa result codes
    into PaySync's unified status vocabulary.

    Every M-Pesa code must be explicitly handled here.
    Unknown codes are treated as retryable failures — safe default.

    This class is the ONLY place in PaySync that knows about
    M-Pesa result codes. If Safaricom adds a new code, update here.
    Nothing else changes.
    """

    # ── Result code definitions ───────────────────────────────────────────────

    SUCCESS_CODE = 0

    # Permanent failures — retrying will never help
    PERMANENT_FAILURES = {
        1032: "Transaction cancelled by user",
        2001: "Wrong PIN entered — account may be locked",
        1001: "Insufficient funds in customer account",
        1025: "Transaction limit reached for this account",
        17:   "M-Pesa system internal error — contact Safaricom",
        26:   "System busy — but treated as permanent to avoid abuse",
    }

    # Retryable failures — transient, worth trying again
    RETRYABLE_FAILURES = {
        1037: "Customer unreachable — STK push not delivered",
        1019: "Transaction expired before customer responded",
        1:    "Insufficient balance (temporary)",
        2:    "Less than minimum transaction value",
        6:    "Transaction failed — retry recommended",
        9:    "Request timeout from Daraja",
        11:   "Daraja service temporarily unavailable",
        12:   "Invalid parameter — check request",
        13:   "Invalid shortcode",
        14:   "Invalid Access Token",
        15:   "Invalid initiator information",
        16:   "Temporary error — retry",
        21:   "Transaction in process",
        22:   "Invalid transaction type",
        23:   "Invalid payment type",
    }

    def normalize_callback_result(
        self,
        result_code: int,
        result_desc: str = "",
    ) -> NormalizedStatus:
        """
        Translate an M-Pesa callback result into a NormalizedStatus.

        Called by CallbackProcessor after parsing the raw callback.

        Args:
            result_code: Integer from M-Pesa's ResultCode field
            result_desc: String from M-Pesa's ResultDesc field

        Returns:
            NormalizedStatus with all fields populated
        """
        result_code = int(result_code)

        # ── Success ───────────────────────────────────────────────────────────
        if result_code == self.SUCCESS_CODE:
            normalized = NormalizedStatus(
                status='success',
                is_retryable=False,
                is_permanent=True,
                reason="Payment completed successfully.",
                provider_code=result_code,
                provider_message=result_desc,
            )
            logger.info(
                f"Status normalized: ResultCode={result_code} → success"
            )
            return normalized

        # ── Permanent failure ─────────────────────────────────────────────────
        if result_code in self.PERMANENT_FAILURES:
            reason = self.PERMANENT_FAILURES[result_code]
            normalized = NormalizedStatus(
                status='failed',
                is_retryable=False,
                is_permanent=True,
                reason=reason,
                provider_code=result_code,
                provider_message=result_desc,
            )
            logger.warning(
                f"Status normalized: ResultCode={result_code} → "
                f"failed (permanent) | {reason}"
            )
            return normalized

        # ── Retryable failure ─────────────────────────────────────────────────
        if result_code in self.RETRYABLE_FAILURES:
            reason = self.RETRYABLE_FAILURES[result_code]
            normalized = NormalizedStatus(
                status='failed',
                is_retryable=True,
                is_permanent=False,
                reason=reason,
                provider_code=result_code,
                provider_message=result_desc,
            )
            logger.warning(
                f"Status normalized: ResultCode={result_code} → "
                f"failed (retryable) | {reason}"
            )
            return normalized

        # ── Unknown code — safe default: retryable failure ────────────────────
        # We don't know what this code means, so we don't permanently fail.
        # Log it loudly so you can add it to the map above.
        logger.error(
            f"UNKNOWN M-Pesa ResultCode: {result_code} | "
            f"ResultDesc: {result_desc} | "
            f"Treating as retryable failure. Add this code to "
            f"MpesaStatusNormalizer to handle explicitly."
        )
        return NormalizedStatus(
            status='failed',
            is_retryable=True,
            is_permanent=False,
            reason=f"Unknown provider result: {result_desc or result_code}",
            provider_code=result_code,
            provider_message=result_desc,
        )

    def normalize_stk_initiation_failure(
        self,
        error_code: Optional[str] = None,
        error_message: str = "",
    ) -> NormalizedStatus:
        """
        Normalize failures that happen at STK Push initiation time —
        before the customer even sees the prompt.

        These are different from callback failures: they happen when
        Daraja rejects our request outright, or we can't reach Daraja.

        Args:
            error_code: Daraja error code string (e.g. "400002")
            error_message: Error description from Daraja or our network layer

        Returns:
            NormalizedStatus — always retryable unless it's a config error
        """

        # Config errors — retrying won't help, alert the developer
        config_error_indicators = [
            "invalid consumer",
            "invalid access token",
            "wrong credentials",
            "2001",
            "400002",
        ]

        error_lower = (error_message or "").lower()
        is_config_error = any(
            indicator in error_lower
            for indicator in config_error_indicators
        )

        if is_config_error:
            logger.critical(
                f"STK Push config error — check your Daraja credentials! "
                f"Code: {error_code} | Message: {error_message}"
            )
            return NormalizedStatus(
                status='failed',
                is_retryable=False,
                is_permanent=True,
                reason=f"Payment provider configuration error. Contact support.",
                provider_code=None,
                provider_message=error_message,
            )

        # All other initiation failures are treated as transient
        logger.warning(
            f"STK Push initiation failure — treating as retryable. "
            f"Code: {error_code} | Message: {error_message}"
        )
        return NormalizedStatus(
            status='failed',
            is_retryable=True,
            is_permanent=False,
            reason=f"Payment initiation failed — will retry. ({error_message})",
            provider_code=None,
            provider_message=error_message,
        )


class StatusNormalizerFactory:
    """
    Returns the correct normalizer for a given payment provider.

    Today: only M-Pesa.
    Tomorrow: Airtel Money, Equitel, bank transfers — add here only.

    Usage:
        normalizer = StatusNormalizerFactory.get('mpesa')
        result = normalizer.normalize_callback_result(result_code, result_desc)
    """

    _registry = {
        'mpesa': MpesaStatusNormalizer,
    }

    @classmethod
    def get(cls, provider: str) -> MpesaStatusNormalizer:
        normalizer_class = cls._registry.get(provider.lower())
        if not normalizer_class:
            raise ValueError(
                f"No status normalizer registered for provider '{provider}'. "
                f"Available: {list(cls._registry.keys())}"
            )
        return normalizer_class()

    @classmethod
    def register(cls, provider: str, normalizer_class):
        """
        Register a new provider normalizer at runtime.
        Call this in your app's AppConfig.ready() when adding providers.
        """
        cls._registry[provider] = normalizer_class
        logger.info(f"Registered status normalizer for provider: {provider}")