from django.contrib import admin
from .models import APIClient, APIRequestLog


@admin.register(APIClient)
class APIClientAdmin(admin.ModelAdmin):
    list_display  = ('name', 'source_system', 'status',
                     'rate_limit_per_minute', 'last_used_at', 'created_at')
    list_filter   = ('status',)
    readonly_fields = ('key_hash', 'last_used_at', 'created_at', 'updated_at')
    # key_hash is readonly — no one should be able to see or change it via UI


@admin.register(APIRequestLog)
class APIRequestLogAdmin(admin.ModelAdmin):
    list_display  = ('client', 'method', 'endpoint',
                     'status_code', 'ip_address', 'created_at')
    list_filter   = ('client', 'method', 'status_code')
    readonly_fields = ('client', 'endpoint', 'method',
                       'ip_address', 'status_code', 'created_at')