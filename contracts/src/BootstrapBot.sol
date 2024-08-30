// SPDX-License-Identifier: MIT
pragma solidity ^0.8.13;

import "@openzeppelin/contracts/utils/math/SafeMath.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

import "./interfaces/IUniswapV2Router02.sol";
import "./interfaces/IUniswapV2Factory.sol";
import "./interfaces/IUniswapV2Pair.sol";
import "./interfaces/IERC20.sol";

import "./AbstractBot.sol";

contract BootstrapBot is Ownable {
  using SafeMath for uint256;
  uint16 internal constant DEADLINE_BLOCK_DELAY = 10;

  address private _router;
  address private _factory;
  address private _weth;

  constructor(address router, address factory, address weth) {
    _router = router;
    _factory = factory;
    _weth = weth;
  }

  function approveToken(address router, address token, uint256 amount) external onlyOwner {
    IERC20(token).approve(router, amount);
  }

  function addLiquidity(address erc20, uint256 amountTokenDesired) external onlyOwner payable {
    require(msg.value >0, "Message value MUST be greater than zero");

    // add liquidity (thus create pair inherently)
    uint256 amountTokenMin = amountTokenDesired - amountTokenDesired.div(10_000).mul(5);
    uint256 amountETHMin = msg.value - msg.value.div(10_000).mul(5);

    IUniswapV2Router02(_router).addLiquidityETH{value: msg.value}(
      erc20,
      amountTokenDesired,
      amountTokenMin,
      amountETHMin,
      owner(),
      block.timestamp + DEADLINE_BLOCK_DELAY
    );
  }
}