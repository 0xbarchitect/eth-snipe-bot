// SPDX-License-Identifier: MIT
pragma solidity ^0.8.13;

import "@openzeppelin/contracts/utils/math/SafeMath.sol";

import "./interfaces/IUniswapV2Router02.sol";
import "./interfaces/IUniswapV2Factory.sol";
import "./interfaces/IUniswapV2Pair.sol";
import "./interfaces/IERC20.sol";

import "./AbstractBot.sol";

contract SnipeBot is AbstractBot {
  using SafeMath for uint256;

  fallback() external payable {}

  receive() external payable {}

  function buy(address erc20, uint256 deadline) external payable returns (uint[] memory amounts) {
    (address owner, , , ) = config();
    require(owner == msg.sender, "Unauthorized");

    // long step : swap native for token
    uint8 tokenId = IUniswapV2Pair(_getPair(erc20)).token0() == erc20 ? 0 : 1;

    (uint256 reserve0, uint256 reserve1, ) = IUniswapV2Pair(_getPair(erc20)).getReserves();
    uint256 reserveToken = tokenId == 0 ? reserve0 : reserve1;
    uint256 reserveNative = tokenId == 0 ? reserve1 : reserve0;
    uint256 amountTokenOut = reserveToken - reserveToken.mul(reserveNative).div(reserveNative + msg.value);

    return _swapNativeForToken(erc20, msg.value, amountTokenOut.mul(90).div(100), address(this), deadline);
  }

  function sell(address erc20, address to, uint256 deadline) external returns (uint[] memory amounts) {
    (address owner, address _router, , ) = config();
    require(owner == msg.sender, "Unauthorized");

    // short step : swap token for native
    uint256 balance = IERC20(erc20).balanceOf(address(this));
    IERC20(erc20).approve(_router, balance);
    return _swapTokenForNative(erc20, balance, 0, payable(to), deadline);
  }

  function inspect_transfer(address erc20, uint256 amount) external returns (uint256 received) {
    (address owner, , , ) = config();
    require(owner == msg.sender, "Unauthorized");

    bool success = IERC20(erc20).transferFrom(msg.sender, address(this), amount);
    require(success, "Transfer failed");
    return IERC20(erc20).balanceOf(address(this));
  }
}