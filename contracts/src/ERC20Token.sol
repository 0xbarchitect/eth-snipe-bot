// SPDX-License-Identifier: MIT
pragma solidity ^0.8.13;

import "@openzeppelin/contracts/utils/math/SafeMath.sol";
import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract ERC20Token is Ownable, ERC20 {
    uint256 public constant MAX_SUPPLY = 1000_000_000 * 10 ** 18;

    constructor() ERC20("DUMMY", "DUMMY") {
        _mint(_msgSender(), MAX_SUPPLY);
    }

    function burn(uint256 amount) public {
        _burn(_msgSender(), amount);
    }
}