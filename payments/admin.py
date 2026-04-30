from django.contrib import admin
from .models import Payment, PaymentAttempt, CallbackLog


class PaymentAttemptInline(admin.TabularInline):
    model = PaymentAttempt
    extra = 0
    readonly_fields = ('attempt_number', 'status', 'mpesa_checkout_request_id',
                       'response_payload', 'error_message', 'created_at')
    can_delete = False  # Protect audit trail from admin UI too


class CallbackLogInline(admin.TabularInline):
    model = CallbackLog
    extra = 0
    readonly_fields = ('raw_payload', 'processed', 'checkout_request_id',
                       'processing_error', 'ip_address', 'created_at')
    can_delete = False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('reference', 'source_system', 'external_reference',
                    'amount', 'phone_number', 'status', 'provider', 'created_at')
    list_filter = ('status', 'provider', 'source_system')
    search_fields = ('reference', 'external_reference', 'phone_number')
    readonly_fields = ('reference', 'created_at', 'updated_at')
    inlines = [PaymentAttemptInline]


@admin.register(PaymentAttempt)
class PaymentAttemptAdmin(admin.ModelAdmin):
    list_display = ('payment', 'attempt_number', 'status',
                    'mpesa_checkout_request_id', 'created_at')
    list_filter = ('status',)
    readonly_fields = ('created_at', 'updated_at')
    inlines = [CallbackLogInline]


@admin.register(CallbackLog)
class CallbackLogAdmin(admin.ModelAdmin):
    list_display = ('checkout_request_id', 'processed',
                    'processing_error', 'ip_address', 'created_at')
    list_filter = ('processed',)
    readonly_fields = ('raw_payload', 'created_at')
    search_fields = ('checkout_request_id',)