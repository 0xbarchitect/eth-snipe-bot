import os
import logging
import requests
from decimal import Decimal

import sys # for testing
sys.path.append('..')

from helpers import constants

class GasHelper:
    def __init__(self, etherscan_api_url, api_keys) -> None:
        self.etherscan_api_url=etherscan_api_url
        self.api_keys = api_keys.split(',')

        self.counter=0

    def select_api_key(self):
        self.counter+=1
        return self.api_keys[self.counter % len(self.api_keys)]

    def get_base_gas_price(self):
        r=requests.get(f"{self.etherscan_api_url}/api?module=gastracker&action=gasoracle&apikey={self.select_api_key()}")
        if r.status_code==constants.STATUS_CODE_SUCCESS:
            res=r.json()
            if res.get('result') is not None and res['result']['suggestBaseFee'] is not None:
                return Decimal(res['result']['suggestBaseFee'])
        return None

if __name__=='__main__':
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    helper = GasHelper(os.environ.get('ETHERSCAN_API_URL'), os.environ.get('BASESCAN_API_KEYS'))
    print(helper.get_base_gas_price())
