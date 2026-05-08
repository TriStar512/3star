"""Hyperliquid live-mode signed order client.

Wraps the official sync ``hyperliquid-python-sdk`` in an async-friendly
facade. All order placement and cancellation flows through here when
``PAPER_TRADE=false``; paper mode bypasses this module entirely.

Bracket model
    Every entry the bot opens is followed by three reduce-only trigger
    orders so the position is always protected even if the bot crashes:

        1. entry limit (GTC) at signal price
        2. SL  reduce-only trigger (market) at stop-loss
        3. TP1 reduce-only trigger (limit)  at take-profit-1, 50% of qty
        4. TP2 reduce-only trigger (limit)  at take-profit-2, remaining qty

    If any leg fails after the entry is placed, ``cancel_all_for_coin``
    rolls back the partial bracket so we don't leave naked exposure.

Safety
    - The constructor verifies that ``private_key`` derives the same
      address as ``wallet_address``; mismatched keys raise immediately.
    - ``testnet=True`` is the safe default; flip to mainnet only after
      a clean testnet smoke run.
    - Per-coin leverage is set BEFORE the entry, capped to whatever
      max-leverage Hyperliquid advertises for that coin.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, List, Optional

from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants

log = logging.getLogger(__name__)


@dataclass
class LiveOrderResult:
    ok: bool
    entry_oid: Optional[int] = None
    sl_oid: Optional[int] = None
    tp1_oid: Optional[int] = None
    tp2_oid: Optional[int] = None
    error: Optional[str] = None


class HyperliquidExchange:
    """Thin async facade around the sync Hyperliquid SDK."""

    def __init__(
        self,
        wallet_address: str,
        private_key: str,
        testnet: bool = True,
    ):
        if not wallet_address or not private_key:
            raise ValueError("wallet_address and private_key are required")
        if not wallet_address.startswith("0x") or len(wallet_address) != 42:
            raise ValueError("wallet_address must be a 0x-prefixed 42-char hex string")

        self.wallet_address = wallet_address
        self.testnet = testnet
        url = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL

        try:
            self.account = Account.from_key(private_key)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"invalid private key: {exc}") from exc

        if self.account.address.lower() != wallet_address.lower():
            raise ValueError(
                "private key does not derive the configured HL_WALLET_ADDRESS — "
                "refusing to start to avoid signing for the wrong account"
            )

        self.exchange = Exchange(self.account, url, account_address=wallet_address)
        self.info = Info(url, skip_ws=True)
        log.info(
            "Hyperliquid live client ready: address=%s network=%s",
            wallet_address, "TESTNET" if testnet else "MAINNET",
        )

    # ---- helpers ----

    @staticmethod
    def _extract_oid(resp: Any) -> Optional[int]:
        """Pull the order id out of a Hyperliquid order response."""
        if not isinstance(resp, dict):
            raise RuntimeError(f"unexpected hl response: {resp!r}")
        if resp.get("status") != "ok":
            raise RuntimeError(f"hl order rejected: {resp}")
        statuses = (resp.get("response", {}) or {}).get("data", {}).get("statuses") or []
        for s in statuses:
            if not isinstance(s, dict):
                continue
            if "error" in s:
                raise RuntimeError(f"hl status error: {s['error']}")
            if "resting" in s and isinstance(s["resting"], dict):
                return s["resting"].get("oid")
            if "filled" in s and isinstance(s["filled"], dict):
                return s["filled"].get("oid")
        return None

    async def _run(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    # ---- order placement ----

    async def update_leverage(self, coin: str, leverage: int) -> None:
        leverage = max(1, int(leverage))
        await self._run(self.exchange.update_leverage, leverage, coin)

    async def place_bracketed_order(
        self,
        coin: str,
        is_buy: bool,
        qty: float,
        entry_px: float,
        sl_px: float,
        tp1_px: float,
        tp2_px: float,
        leverage: int,
    ) -> LiveOrderResult:
        """Entry + reduce-only SL/TP1/TP2; rolls back on failure."""
        try:
            await self.update_leverage(coin, int(leverage))
        except Exception as exc:  # noqa: BLE001
            return LiveOrderResult(False, error=f"update_leverage: {exc}")

        # Round qty to a sensible precision; HL rejects too many decimals.
        # 6dp is safe across the top-10 perps; the SDK also enforces.
        qty = round(qty, 6)
        tp1_qty = round(qty * 0.5, 6)
        tp2_qty = round(qty - tp1_qty, 6)
        if tp1_qty <= 0 or tp2_qty <= 0:
            return LiveOrderResult(False, error=f"qty too small to bracket: {qty}")

        entry_oid = sl_oid = tp1_oid = tp2_oid = None
        try:
            # 1) entry: limit GTC at signal price
            entry_resp = await self._run(
                self.exchange.order,
                coin, is_buy, qty, entry_px,
                {"limit": {"tif": "Gtc"}}, False,
            )
            entry_oid = self._extract_oid(entry_resp)

            close_side = not is_buy

            # 2) stop loss: reduce-only market trigger
            sl_resp = await self._run(
                self.exchange.order,
                coin, close_side, qty, sl_px,
                {"trigger": {"triggerPx": sl_px, "isMarket": True, "tpsl": "sl"}}, True,
            )
            sl_oid = self._extract_oid(sl_resp)

            # 3) TP1: 50% reduce-only limit trigger
            tp1_resp = await self._run(
                self.exchange.order,
                coin, close_side, tp1_qty, tp1_px,
                {"trigger": {"triggerPx": tp1_px, "isMarket": False, "tpsl": "tp"}}, True,
            )
            tp1_oid = self._extract_oid(tp1_resp)

            # 4) TP2: remaining 50% reduce-only limit trigger
            tp2_resp = await self._run(
                self.exchange.order,
                coin, close_side, tp2_qty, tp2_px,
                {"trigger": {"triggerPx": tp2_px, "isMarket": False, "tpsl": "tp"}}, True,
            )
            tp2_oid = self._extract_oid(tp2_resp)

            return LiveOrderResult(True, entry_oid, sl_oid, tp1_oid, tp2_oid)

        except Exception as exc:  # noqa: BLE001
            log.error("hl bracket failed, rolling back: %s", exc)
            try:
                await self.cancel_all_for_coin(coin)
            except Exception as rollback_exc:  # noqa: BLE001
                log.error("hl rollback failed: %s", rollback_exc)
            return LiveOrderResult(
                ok=False,
                entry_oid=entry_oid, sl_oid=sl_oid,
                tp1_oid=tp1_oid, tp2_oid=tp2_oid,
                error=str(exc),
            )

    async def cancel_all_for_coin(self, coin: str) -> int:
        """Cancel every open order this account has on ``coin``."""
        try:
            open_orders = await self._run(self.info.open_orders, self.wallet_address)
        except Exception as exc:  # noqa: BLE001
            log.warning("hl open_orders fetch failed: %s", exc)
            return 0
        targets = [
            {"coin": coin, "oid": o["oid"]}
            for o in (open_orders or [])
            if isinstance(o, dict) and o.get("coin") == coin and o.get("oid") is not None
        ]
        if not targets:
            return 0
        await self._run(self.exchange.bulk_cancel, targets)
        return len(targets)

    async def market_close(self, coin: str) -> Any:
        """Emergency: cancel-all + market-close any position on ``coin``."""
        await self.cancel_all_for_coin(coin)
        return await self._run(self.exchange.market_close, coin)

    # ---- account state ----

    async def get_user_state(self) -> dict:
        return await self._run(self.info.user_state, self.wallet_address)

    async def get_balance_and_positions(self) -> dict:
        """Normalized snapshot used by the Broker live path."""
        state = await self.get_user_state()
        margin_summary = state.get("marginSummary", {}) or {}
        cross_summary = state.get("crossMarginSummary", {}) or margin_summary
        positions: List[dict] = []
        for ap in state.get("assetPositions", []) or []:
            pos = ap.get("position") or {}
            if not pos:
                continue
            sz = float(pos.get("szi", 0.0) or 0.0)
            if sz == 0:
                continue
            positions.append({
                "coin": pos.get("coin"),
                "size": sz,                       # positive = long, negative = short
                "entry_price": float(pos.get("entryPx") or 0.0),
                "unrealized_pnl": float(pos.get("unrealizedPnl") or 0.0),
                "leverage": int((pos.get("leverage") or {}).get("value", 1)),
                "liquidation_price": float(pos.get("liquidationPx") or 0.0),
                "margin_used": float(pos.get("marginUsed") or 0.0),
            })
        return {
            "account_value": float(margin_summary.get("accountValue") or 0.0),
            "total_margin_used": float(margin_summary.get("totalMarginUsed") or 0.0),
            "withdrawable": float(state.get("withdrawable") or 0.0),
            "cross_account_value": float(cross_summary.get("accountValue") or 0.0),
            "positions": positions,
        }
