import os
from web3 import Web3
from decimal import Decimal

from dotenv import load_dotenv
load_dotenv()

from django.contrib import admin
from django.utils.html import format_html

from console.models import Block, Transaction, Pair, Position, PositionTransaction, BlackList, Bot, \
                            Executor, PnL

class ConsoleAdminSite(admin.AdminSite):
    def index(self, request, extra_context=None):
        extra_context = extra_context or {}

        # executors
        executors = Executor.objects.filter(is_deleted=0).order_by('-id')
        extra_context['executors'] = executors

        # calculate performance
        principal = sum([executor.initial_balance for executor in executors])
        cash = sum([executor.current_balance for executor in executors])
        pnl = (Decimal(cash)-Decimal(principal))/Decimal(principal)*Decimal(100) if principal>0 else 0

        extra_context['principal']=round(principal,6)
        extra_context['cash']=round(cash,6)
        extra_context['pnl']=round(pnl,3)

        # Add your context here
        return super(ConsoleAdminSite, self).index(request, extra_context)
    
    site_header = "Bot Admin"
    site_title = "Bot Admin"
    index_title = "Console"
    index_template = 'index.html'

class NoDeletePermissionModelAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None):
        return False
    
    def has_add_permission(self, request):
        return False
    
class FullPermissionModelAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None):
        return True
    
    def has_add_permission(self, request):
        return True
    
class BlockAdmin(FullPermissionModelAdmin):
    list_filter = ['is_deleted']
    list_display = ('id', 'block_number', 'block_timestamp', 'base_fee', 'gas_used', 'buttons')
    fields = ('block_number', 'block_timestamp', 'base_fee', 'gas_used', 'gas_limit',)
    readonly_fields = ('block_number', 'block_timestamp', 'base_fee', 'gas_used', 'gas_limit',)
    
    @admin.display(description='Actions')
    def buttons(self, obj):
        return format_html(f"""
        <button><a class="btn" href="/admin/console/block/{obj.id}/change/">Edit</a></button>&emsp;
        """)
    
class TransactionAdmin(FullPermissionModelAdmin):
    list_filter = ['is_deleted']
    list_display = ('id', 'block', 'tx_hash', 'sender', 'status', 'buttons')
    fields = ('block', 'tx_hash', 'sender', 'to', 'value', 'gas_limit', 'max_priority_fee_per_gas', 'max_fee_per_gas', 'status',)
    readonly_fields = ('block', 'tx_hash', 'sender', 'to', 'value', 'gas_limit', 'max_priority_fee_per_gas', 'max_fee_per_gas', 'status')
    
    @admin.display(description='Actions')
    def buttons(self, obj):
        return format_html(f"""
        <button><a class="btn" href="/admin/console/transaction/{obj.id}/change/">Edit</a></button>&emsp;
        """)

class PairAdmin(FullPermissionModelAdmin):
    list_filter = ['is_deleted']
    list_display = ('id', 'address', 'token', 'token_index', 'creator', 'deployed_block', 'deployed_at', 'reserve_token', 'reserve_eth', 'buttons')
    fields = ('address', 'token', 'token_index', 'creator', 'reserve_token', 'reserve_eth', 'deployed_block', 'deployed_at',)
    readonly_fields = ('address', 'token', 'token_index', 'creator', 'reserve_token', 'reserve_eth', 'deployed_block', 'deployed_at',)
    
    @admin.display(description='Actions')
    def buttons(self, obj):
        return format_html(f"""
        <button><a class="btn" href="/admin/console/pair/{obj.id}/change/">Edit</a></button>&emsp;
        """)
    
class PositionTransactionInline(admin.TabularInline):
    model = PositionTransaction

class PositionAdmin(FullPermissionModelAdmin):
    inlines = [PositionTransactionInline]

    list_filter = ['is_deleted']
    list_display = ('id', 'pair', 'bot', 'amount', 'purchased_at', 'is_liquidated', 'liquidated_at', 'investment_h', 'returns_h', 'pnl_h', 'buttons')
    fields = ('pair', 'signer', 'bot', 'amount', 'buy_price', 'purchased_at', 'is_liquidated', 'sell_price', 'liquidated_at', 'liquidation_attempts', 'investment', 'returns', 'pnl', 'is_paper',)
    readonly_fields = ('pair', 'signer', 'bot', 'amount', 'buy_price', 'purchased_at', 'is_liquidated', 'sell_price', 'liquidated_at', 'liquidation_attempts', 'investment', 'returns', 'pnl',)
    
    @admin.display(description='Actions')
    def buttons(self, obj):
        return format_html(f"""
        <button><a class="btn" href="/admin/console/position/{obj.id}/change/">Edit</a></button>&emsp;
        """)
    
    @admin.display()
    def investment_h(self, obj):
        if obj.investment is not None:
            return format_html(f"{round(obj.investment, 9)}")
        return format_html(f"-")
    
    @admin.display()
    def returns_h(self, obj):
        if obj.returns is not None:
            return format_html(f"{round(obj.returns, 9)}")
        return format_html(f"-")
    
    @admin.display()
    def pnl_h(self, obj):
        if obj.pnl is not None:
            return format_html(f"{round(obj.pnl, 5)}")
        return format_html(f"-")
    
class BlacklistAdmin(FullPermissionModelAdmin):
    list_filter = ['is_deleted']
    list_display = ('id', 'address', 'frozen_at', 'buttons')
    fields = ('address', 'frozen_at',)
    
    @admin.display(description='Actions')
    def buttons(self, obj):
        return format_html(f"""
        <button><a class="btn" href="/admin/console/blacklist/{obj.id}/change/">Edit</a></button>&emsp;
        """)
    
class BotAdmin(FullPermissionModelAdmin):
    list_filter = ['is_deleted']
    list_display = ('id', 'address', 'owner', 'deployed_at', 'number_used', 'is_failed', 'is_holding', 'buttons')
    fields = ('address', 'owner', 'deployed_at', 'number_used', 'is_failed', 'is_holding',)
    
    @admin.display(description='Actions')
    def buttons(self, obj):
        return format_html(f"""
        <button><a class="btn" href="/admin/console/bot/{obj.id}/change/">Edit</a></button>&emsp;
        """)
    
class PnlAdmin(FullPermissionModelAdmin):
    list_filter = ['is_deleted']
    list_display = ('id', 'timestamp', 'number_positions', 'number_failed', 'hourly_pnl', 'avg_daily_pnl', 'buttons')
    fields = ('timestamp', 'number_positions', 'number_failed', 'hourly_pnl', 'avg_daily_pnl',)
    readonly_fields = ('timestamp', 'number_positions', 'number_failed', 'hourly_pnl', 'avg_daily_pnl',)
    
    @admin.display(description='Actions')
    def buttons(self, obj):
        return format_html(f"""
        <button><a class="btn" href="/admin/console/pnl/{obj.id}/change/">Edit</a></button>&emsp;
        """)
    
class ExecutorAdmin(FullPermissionModelAdmin):
    w3 = Web3(Web3.HTTPProvider(os.environ.get('HTTPS_URL')))

    list_filter = ['is_deleted']
    list_display = ('id', 'address', 'initial_balance_h', 'current_balance', 'pnl', 'created_at', 'buttons')
    fields = ('address', 'initial_balance', 'current_balance', 'pnl')
    readonly_fields = ('address', 'initial_balance', 'current_balance', 'pnl')
    
    @admin.display(description='Actions')
    def buttons(self, obj):
        return format_html(f"""
        <button><a class="btn" href="/admin/console/executor/{obj.id}/change/">Edit</a></button>&emsp;
        """)
    
admin_site = ConsoleAdminSite(name="console_admin")

admin_site.register(Block, BlockAdmin)
admin_site.register(Transaction, TransactionAdmin)
admin_site.register(Pair, PairAdmin)
admin_site.register(Position, PositionAdmin)
admin_site.register(BlackList, BlacklistAdmin)
admin_site.register(Bot, BotAdmin)
admin_site.register(PnL, PnlAdmin)
admin_site.register(Executor, ExecutorAdmin)