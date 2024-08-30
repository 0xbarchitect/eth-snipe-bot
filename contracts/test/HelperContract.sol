// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.13;

import "../src/interfaces/IUniswapV2Router02.sol";
import "../src/interfaces/IUniswapV2Factory.sol";
import "../src/interfaces/IUniswapV2Pair.sol";

import {ERC20Token} from "../src/ERC20Token.sol";

abstract contract HelperContract {
  ERC20Token public token;

  address constant ROUTERV2 = 0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D;
  address constant FACTORYV2 = 0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f;
  address constant WETH = 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2;

  uint256 constant TOTAL_SUPPLY = 1_000_000_000 * 10**18;
  uint256 constant INITIAL_AVAX_RESERVE = 10**18;

  uint16 constant DEADLINE_BLOCK_DELAY = 1000;

  function _getPair() internal view returns (address pair) {
    return IUniswapV2Factory(FACTORYV2).getPair(address(token), WETH);
  }
}