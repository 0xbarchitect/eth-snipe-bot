// SPDX-License-Identifier: MIT
pragma solidity ^0.8.13;

import "@openzeppelin/contracts/utils/math/SafeMath.sol";

import "./interfaces/IUniswapV2Router02.sol";
import "./interfaces/IUniswapV2Factory.sol";
import "./interfaces/IUniswapV2Pair.sol";
import "./interfaces/IERC20.sol";

abstract contract AbstractBot {
  using SafeMath for uint256;

  function config() public view returns (address owner, address router, address factory, address weth) {
    bytes memory footer = new bytes(0x80);
    assembly {
      extcodecopy(address(), add(footer, 0x20), 0x2d, 0x80)
    }
    return abi.decode(footer, (address, address, address, address));
  }

  function _getPair(address erc20) internal view returns (address pair) {
    (, , address _factory, address _weth) = config();
    return IUniswapV2Factory(_factory).getPair(erc20, _weth);
  }

  function _swapNativeForToken(address erc20, uint256 amountETHIn, uint256 amountTokenOut, address to, uint256 deadline) internal returns (uint[] memory amounts) {
    (, address _router, , address _weth) = config();

    address[] memory path = new address[](2);
    path[0] = _weth;
    path[1] = erc20;

    return IUniswapV2Router02(_router).swapExactETHForTokens{value: amountETHIn}(
      amountTokenOut,
      path,
      to,
      deadline
    );
  }

  function _swapTokenForNative(address erc20, uint256 amountTokenIn, uint256 amountETHOutMin, address payable to, uint256 deadline) internal returns (uint[] memory amounts) {
    (, address _router, , address _weth) = config();

    address[] memory path = new address[](2);
    path[0] = erc20;
    path[1] = _weth;

    return IUniswapV2Router02(_router).swapExactTokensForETH(
      amountTokenIn,
      amountETHOutMin,
      path,
      to,
      deadline
    );
  }

}