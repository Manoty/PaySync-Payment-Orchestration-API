import base64
import logging
import requests
from datetime import datetime
from django.conf import settings

logger = logging.getLogger(__name__)


class MpesaError(Exception):
    """Raised when Daraja API returns an error we can't recover from."""
    pass


class MpesaService:
    """
    Single-responsibility wrapper around Safaricom Daraja API.
    
    This class is the ONLY place in PaySync that knows about:
    - Daraja endpoints
    - Token management
    - Password generation
    - Request/response shapes
    
    Everything else calls this service and works with clean results.
    """

    SANDBOX_BASE = "https://sandbox.safaricom.co.ke"
    PRODUCTION_BASE = "https://api.safaricom.co.ke"

    def __init__(self):
        self.consumer_key = settings.MPESA_CONSUMER_KEY
        self.consumer_secret = settings.MPESA_CONSUMER_SECRET
        self.shortcode = settings.MPESA_SHORTCODE
        self.passkey = settings.MPESA_PASSKEY
        self.callback_url = settings.MPESA_CALLBACK_URL
        self.env = settings.MPESA_ENV  # 'sandbox' or 'production'

        self.base_url = (
            self.SANDBOX_BASE if self.env == 'sandbox'
            else self.PRODUCTION_BASE
        )

    # ── Token Management ──────────────────────────────────────────────────────

    def get_access_token(self):
        """
        Fetches a short-lived OAuth token from Daraja.
        
        Tokens expire after 1 hour. For now we fetch a fresh one
        per request — simple and correct. In production you'd cache
        this in Redis with a 55-minute TTL to avoid the extra round-trip.
        """
        url = f"{self.base_url}/oauth/v1/generate?grant_type=client_credentials"

        # Daraja uses HTTP Basic Auth with consumer key:secret
        credentials = f"{self.consumer_key}:{self.consumer_secret}"
        encoded = base64.b64encode(credentials.encode()).decode('utf-8')

        headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            token = response.json().get('access_token')

            if not token:
                raise MpesaError("Daraja returned empty access token.")

            logger.info("M-Pesa access token fetched successfully.")
            return token

        except requests.exceptions.Timeout:
            logger.error("Timeout fetching M-Pesa access token.")
            raise MpesaError("M-Pesa authentication timed out.")

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch M-Pesa token: {str(e)}")
            raise MpesaError(f"M-Pesa authentication failed: {str(e)}")

    # ── Password Generation ───────────────────────────────────────────────────

    def _generate_password(self, timestamp):
        """
        Daraja STK Push password = Base64(shortcode + passkey + timestamp).
        
        The timestamp must match exactly between password generation
        and the request body — both use the same value.
        """
        raw = f"{self.shortcode}{self.passkey}{timestamp}"
        encoded = base64.b64encode(raw.encode()).decode('utf-8')
        return encoded

    def _get_timestamp(self):
        """
        Returns current time in Daraja's required format: YYYYMMDDHHmmss
        Must be EAT (East Africa Time) — handled by Django's TIME_ZONE setting.
        """
        return datetime.now().strftime('%Y%m%d%H%M%S')

    # ── STK Push ─────────────────────────────────────────────────────────────

    def initiate_stk_push(self, payment, attempt):
        """
        Sends an STK Push request to Daraja.
        
        Args:
            payment: Payment model instance
            attempt: PaymentAttempt model instance (the current attempt)
        
        Returns:
            dict with keys:
                success (bool)
                checkout_request_id (str | None)
                response_payload (dict)
                error_message (str | None)
        
        This method NEVER raises — it always returns a result dict.
        The caller decides what to do with failures.
        Why? Because network errors are expected, not exceptional.
        """
        result = {
            "success": False,
            "checkout_request_id": None,
            "response_payload": {},
            "error_message": None,
        }

        try:
            token = self.get_access_token()
        except MpesaError as e:
            result["error_message"] = str(e)
            logger.error(f"STK Push aborted — token failure: {str(e)}")
            return result

        timestamp = self._get_timestamp()
        password = self._generate_password(timestamp)

        url = f"{self.base_url}/mpesa/stkpush/v1/processrequest"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload = {
            # The till/paybill number
            "BusinessShortCode": self.shortcode,
            # Base64(shortcode + passkey + timestamp)
            "Password": password,
            # YYYYMMDDHHmmss
            "Timestamp": timestamp,
            # CustomerPayBillOnline = pay to paybill
            # CustomerBuyGoodsOnline = pay to till
            "TransactionType": "CustomerPayBillOnline",
            # Must be integer — M-Pesa rejects decimals
            "Amount": int(payment.amount),
            # Phone number in 2547XXXXXXXX format
            "PartyA": payment.phone_number,
            # Same as BusinessShortCode for STK Push
            "PartyB": self.shortcode,
            # The number receiving the push notification
            "PhoneNumber": payment.phone_number,
            # Your public endpoint — Daraja POSTs result here
            "CallBackURL": self.callback_url,
            # Shown to customer on their phone
            "AccountReference": str(payment.reference)[:12],
            # Shown to customer on their phone (max 13 chars)
            "TransactionDesc": f"Payment {payment.source_system[:8]}",
        }

        logger.info(
            f"Sending STK Push | reference={payment.reference} | "
            f"phone={payment.phone_number} | amount={payment.amount} | "
            f"attempt={attempt.attempt_number}"
        )

        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=30,
            )

            response_data = response.json()
            result["response_payload"] = response_data

            logger.info(f"Daraja raw response: {response_data}")

            # Daraja returns ResponseCode "0" for accepted requests
            # "accepted" ≠ "paid" — it means the push was sent to the phone
            if response_data.get("ResponseCode") == "0":
                result["success"] = True
                result["checkout_request_id"] = response_data.get(
                    "CheckoutRequestID"
                )
                logger.info(
                    f"STK Push accepted | "
                    f"CheckoutRequestID={result['checkout_request_id']}"
                )
            else:
                error_msg = response_data.get(
                    "errorMessage",
                    response_data.get("ResponseDescription", "Unknown error")
                )
                result["error_message"] = error_msg
                logger.warning(
                    f"STK Push rejected by Daraja: {error_msg} | "
                    f"ResponseCode={response_data.get('ResponseCode')}"
                )

        except requests.exceptions.Timeout:
            result["error_message"] = "STK Push request timed out."
            logger.error(
                f"STK Push timeout | reference={payment.reference}"
            )

        except requests.exceptions.RequestException as e:
            result["error_message"] = f"Network error: {str(e)}"
            logger.error(
                f"STK Push network error | reference={payment.reference} | "
                f"error={str(e)}"
            )

        except ValueError:
            result["error_message"] = "Invalid JSON response from Daraja."
            logger.error(
                f"Daraja returned non-JSON | reference={payment.reference}"
            )

        return result