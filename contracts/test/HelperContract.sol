// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.13;

import "../src/interfaces/IUniswapV2Router02.sol";
import "../src/interfaces/IUniswapV2Factory.sol";
import "../src/interfaces/IUniswapV2Pair.sol";

import {ERC20Token} from "../src/ERC20Token.sol";

abstract contract HelperContract {
  ERC20Token public token;

  address constant ROUTERV2 = 0x10ED43C718714eb63d5aA57B78B54704E256024E;
  address constant FACTORYV2 = 0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73;
  address constant WETH = 0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c;

  uint256 constant TOTAL_SUPPLY = 1_000_000_000 * 10**18;
  uint256 constant INITIAL_AVAX_RESERVE = 10**18;

  uint16 constant DEADLINE_BLOCK_DELAY = 1000;

  function _getPair() internal view returns (address pair) {
    return IUniswapV2Factory(FACTORYV2).getPair(address(token), WETH);
  }
}