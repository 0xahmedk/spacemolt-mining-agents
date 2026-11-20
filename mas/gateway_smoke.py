"""Live, READ-ONLY smoke test of the MCP gateway against the real game.

    python -m mas.gateway_smoke --pilot Prac-Ahmed1

Does: MCP initialize -> tool schema discovery -> authenticated login ->
get_status / get_system / get_poi (parsed) -> lists unsettled ledger actions.
Changes nothing in the game.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from mas.mcp_gateway import GameGateway
from mas.parsers import parse_status, parse_table


async def main(pilot: str):
    async with GameGateway(pilot, agent='smoke-test') as gw:
        print(f'\n[PASS] MCP initialized, {len(gw.schemas)} tool schemas loaded, logged in as {pilot}')
        raw = await gw.query('spacemolt', 'get_status', task_id='smoke')
        status = parse_status(raw.text)
        print('[PASS] get_status parsed from text:')
        print(json.dumps(status, indent=2))
        # The docs server says every reply carries typed JSON (structuredContent, type V2GameState).
        # Check whether the MCP surface actually delivers it to us.
        sc = raw.structured
        if isinstance(sc, dict):
            print('[INFO] structuredContent PRESENT, top-level keys:', sorted(sc))
            for section in ('player', 'ship', 'location'):
                if isinstance(sc.get(section), dict):
                    print(f'       {section} keys:', sorted(sc[section])[:25])
        else:
            print('[INFO] structuredContent ABSENT on MCP (type:', type(sc).__name__, ') -> keep text parsers')
        system = (await gw.query('spacemolt', 'get_system', task_id='smoke')).text
        pois = parse_table(system, 'POIs (')
        print(f'[PASS] get_system: {len(pois)} POIs ->', ', '.join(f"{p['id']}({p.get('type')})" for p in pois))
        poi = (await gw.query('spacemolt', 'get_poi', task_id='smoke')).text
        print('[PASS] get_poi first line:', poi.splitlines()[0] if poi else '(empty)')
        unsettled = gw.ledger.unsettled(pilot)
        print(f'[INFO] unsettled ledger actions for {pilot}: {len(unsettled)}')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--pilot', required=True)
    asyncio.run(main(p.parse_args().pilot))
