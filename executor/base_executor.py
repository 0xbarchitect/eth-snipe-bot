import os
import logging
from decimal import Decimal

from web3 import Web3
from web3.middleware import geth_poa_middleware, construct_sign_and_send_raw_middleware

import django
from django.utils.timezone import make_aware
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "admin.settings")
django.setup()
import console.models

import sys # for testing
sys.path.append('..')

from library import Singleton
from data import W3Account

ALLOWANCE_TOKEN_AMOUNT = 10**6
MINIMUM_AVAX_BALANCE = 0.01

class BaseExecutor(metaclass=Singleton):
    def __init__(self, http_url, treasury_key, executor_keys, order_receiver, report_sender, gas_limit, max_fee_per_gas, max_priority_fee_per_gas, deadline_delay) -> None:
        self.http_url = http_url
        self.w3 = Web3(Web3.HTTPProvider(http_url))
        if self.w3.is_connected() == True:
            logging.info(f"web3 provider {http_url} connected")

        self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)

        self.treasury = self.w3.eth.account.from_key(treasury_key)
        self.w3.middleware_onion.add(construct_sign_and_send_raw_middleware(self.treasury))
        self.w3.eth.default_account = self.treasury.address

        self.accounts = [self.build_w3_account(priv_key) for priv_key in executor_keys]
        self.insert_executors_db()

        self.gas_limit = gas_limit
        self.max_fee_per_gas = max_fee_per_gas
        self.max_priority_fee_per_gas = max_priority_fee_per_gas
        self.deadline_delay = deadline_delay

        self.order_receiver = order_receiver
        self.report_sender = report_sender

    def build_w3_account(self, private_key) -> W3Account:
        acct = self.w3.eth.account.from_key(private_key)

        return W3Account(
            acct,
            private_key,
        )
    
    def insert_executors_db(self):
        addresses = [acct.w3_account.address.lower() for acct in self.accounts]

        # delete old executors
        console.models.Executor.objects.exclude(address__in=addresses).delete()
        logging.info(f"EXECUTOR Delete all old executors...")

        # insert current executors to db
        for address in addresses:
            executor = console.models.Executor.objects.filter(address=address.lower()).first()
            if executor is None:
                executor = console.models.Executor(
                    address=address.lower(),
                    initial_balance=Web3.from_wei(self.w3.eth.get_balance(Web3.to_checksum_address(address)),'ether')
                )
                executor.save()
                logging.info(f"EXECUTOR Create executor {address} in DB #{executor.id}")
            else:
                logging.info(f"EXECUTOR Executor {address} existed #{executor.id}")

    def get_block_timestamp(self):
        block = self.w3.eth.get_block('latest')
        return block['timestamp']




    