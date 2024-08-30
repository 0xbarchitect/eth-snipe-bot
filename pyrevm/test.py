import os
from pyrevm import EVM, Env, BlockEnv
import logging

import sys # for testing
sys.path.append('..')

from helpers import load_contract_bin, encode_address, encode_uint, func_selector, timer_decorator

address = "0xA8bAd437e552AADF89f213c34eD97266160B06E0"  # vitalik.eth
address2 = "0x9DDBbB468880906beb448c898c3F7d53F49F8144"

fork_url = os.environ.get('HTTPS_URL')

@timer_decorator
def simulate_call():
    # set up an evm
    evm = EVM(
        # can fork from a remote node
        fork_url=fork_url,
        # can set tracing to true/false
        #tracing=True,
        # can configure the environment
        # env=Env(
        #     block=BlockEnv(timestamp=100)
        # )
    )

    vb_before = evm.basic(address)
    print(vb_before)

    code = load_contract_bin(f"{os.path.dirname(__file__)}/bytecodes/dummy_avex.bin")
    deployed_at = evm.deploy(address, code)

    print(f"deployed at {deployed_at}")
    print(f"func selector {func_selector('balanceOf(address)')}")

    result = evm.message_call(
        address,
        deployed_at,
        calldata=bytes.fromhex(
            func_selector('balanceOf(address)') + f"{encode_address(address)}"
        )
    )

    print(f"result local {int.from_bytes(result, 'big')}")

    result2 = evm.message_call(
        address,
        address2,
        calldata=bytes.fromhex(
            func_selector('balanceOf(address)') + f"{encode_address(address)}"
        )
    )

    print(f"result onchain {int.from_bytes(result2, 'big')}")

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    simulate_call()

