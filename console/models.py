from django.db import models
from datetime import datetime

import os
from web3 import Web3
from decimal import Decimal

# Create your models here.
class Block(models.Model):
    class Meta():
        db_table = 'block'

    id = models.BigAutoField(primary_key=True)
    block_number = models.BigIntegerField(unique=True)
    block_timestamp = models.BigIntegerField(null=True, default=0)
    base_fee = models.BigIntegerField(null=True, default=0)
    gas_used = models.BigIntegerField(null=True, default=0)
    gas_limit = models.BigIntegerField(null=True, default=0)

    created_at = models.DateTimeField(null=True,auto_now_add=True)
    updated_at = models.DateTimeField(null=True,auto_now=True)
    is_deleted = models.IntegerField(null=True,default=0)

    def __str__(self) -> str:
        return str(self.block_number)
    
class Transaction(models.Model):
    class Meta():
        db_table = 'transaction'

    id = models.BigAutoField(primary_key=True)
    tx_hash = models.CharField(max_length=66, unique=True)
    block = models.ForeignKey(Block, on_delete=models.DO_NOTHING)
    sender = models.CharField(max_length=42, null=True)
    to = models.CharField(max_length=42, null=True)    
    value = models.FloatField(null=True, default=0)
    gas_limit = models.FloatField(null=True, default=0)
    max_priority_fee_per_gas = models.FloatField(null=True, default=0)
    max_fee_per_gas = models.FloatField(null=True, default=0)
    status = models.IntegerField(null=True, default=0)

    created_at = models.DateTimeField(null=True,auto_now_add=True)
    updated_at = models.DateTimeField(null=True,auto_now=True)
    is_deleted = models.IntegerField(null=True,default=0)

    def __str__(self) -> str:
        return str(self.tx_hash)

class Pair(models.Model):
    class Meta():
        db_table = 'pair'
        indexes = [
            models.Index(fields=['creator']),
        ]

    id = models.BigAutoField(primary_key=True)
    address = models.CharField(max_length=42, unique=True)
    token = models.CharField(max_length=42)
    token_index = models.IntegerField(null=True, default=0)
    reserve_token = models.FloatField(null=True, default=0)
    reserve_eth = models.FloatField(null=True, default=0)
    deployed_at = models.DateTimeField(null=True)
    creator = models.CharField(max_length=42, null=True)
    deployed_block = models.IntegerField(null=True, default=0)

    created_at = models.DateTimeField(null=True,auto_now_add=True)
    updated_at = models.DateTimeField(null=True,auto_now=True)
    is_deleted = models.IntegerField(null=True,default=0)

    def __str__(self) -> str:
        return f"{self.address}"
    
class Position(models.Model):
    class Meta():
        db_table = 'position'

    id = models.BigAutoField(primary_key=True)
    pair = models.ForeignKey(Pair, on_delete=models.DO_NOTHING)
    amount = models.FloatField(null=True, default=0)
    buy_price = models.FloatField(null=True, default=0)
    purchased_at = models.DateTimeField(null=True)
    is_liquidated = models.IntegerField(null=True, default=0)
    liquidated_at = models.DateTimeField(null=True)
    sell_price = models.FloatField(null=True, default=0)
    liquidation_attempts = models.IntegerField(null=True, default=0)
    pnl = models.FloatField(null=True, default=0)
    signer = models.CharField(max_length=42, null=True)
    bot = models.CharField(max_length=42, null=True)
    investment = models.FloatField(null=True)
    returns = models.FloatField(null=True)
    is_paper = models.BooleanField(null=True, default=False)

    created_at = models.DateTimeField(null=True,auto_now_add=True)
    updated_at = models.DateTimeField(null=True,auto_now=True)
    is_deleted = models.IntegerField(null=True,default=0)

    def __str__(self) -> str:
        return f"{self.pair}"
    
class PositionTransaction(models.Model):
    class Meta():
        db_table = 'position_transaction'

    id = models.BigAutoField(primary_key=True)
    position = models.ForeignKey(Position, on_delete=models.DO_NOTHING)
    transaction = models.ForeignKey(Transaction, on_delete=models.DO_NOTHING)
    is_buy = models.IntegerField(null=True,default=0)

    created_at = models.DateTimeField(null=True,auto_now_add=True)
    updated_at = models.DateTimeField(null=True,auto_now=True)
    is_deleted = models.IntegerField(null=True,default=0)

    def __str__(self) -> str:
        return f"{self.pair}"
    
class BlackList(models.Model):
    class Meta():
        db_table = 'blacklist'

    id = models.BigAutoField(primary_key=True)
    address = models.CharField(max_length=42, unique=True, null=True)
    frozen_at = models.DateTimeField(null=True)

    created_at = models.DateTimeField(null=True,auto_now_add=True)
    updated_at = models.DateTimeField(null=True,auto_now=True)
    is_deleted = models.IntegerField(null=True,default=0)

    def __str__(self) -> str:
        return f"{self.address}"
    
class Bot(models.Model):
    class Meta():
        db_table = 'bot'

    id = models.BigAutoField(primary_key=True)
    address = models.CharField(max_length=42, unique=True)
    owner = models.CharField(max_length=42)
    deployed_at = models.DateTimeField(null=True)
    number_used = models.IntegerField(null=True, default=0)
    is_failed = models.BooleanField(null=True, default=False)
    is_holding = models.BooleanField(null=True, default=False)

    created_at = models.DateTimeField(null=True,auto_now_add=True)
    updated_at = models.DateTimeField(null=True,auto_now=True)
    is_deleted = models.IntegerField(null=True,default=0)

    def __str__(self) -> str:
        return f"{self.address}"
    
class PnL(models.Model):
    class Meta():
        db_table = 'pnl'

    id = models.BigAutoField(primary_key=True)
    timestamp = models.CharField(max_length=20, unique=True)
    number_positions = models.IntegerField(null=True, default=0)
    hourly_pnl = models.FloatField(null=True, default=0)
    avg_daily_pnl = models.FloatField(null=True, default=0)
    number_failed = models.IntegerField(null=True, default=0)

    created_at = models.DateTimeField(null=True,auto_now_add=True)
    updated_at = models.DateTimeField(null=True,auto_now=True)
    is_deleted = models.IntegerField(null=True,default=0)

    def __str__(self) -> str:
        return f"{self.timestamp}"
    
class Executor(models.Model):
    class Meta():
        db_table = "executor"

    w3 = Web3(Web3.HTTPProvider(os.environ.get('HTTPS_URL')))

    id = models.BigAutoField(primary_key=True)
    address = models.CharField(max_length=42, unique=True)
    initial_balance = models.FloatField(null=True, default=0)

    created_at = models.DateTimeField(null=True,auto_now_add=True)
    updated_at = models.DateTimeField(null=True,auto_now=True)
    is_deleted = models.IntegerField(null=True,default=0)

    @property
    def initial_balance_h(self):
        return round(self.initial_balance, 6)
    
    @property
    def current_balance(self):
        return round(Web3.from_wei(self.w3.eth.get_balance(Web3.to_checksum_address(self.address)),'ether'),6)

    @property
    def pnl(self):
        return round((Decimal(self.current_balance)-Decimal(self.initial_balance))/Decimal(self.initial_balance)*Decimal(100), 3) if self.initial_balance>0 else 0

    def __str__(self) -> str:
        return f"{self.address}"
    

