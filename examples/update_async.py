# This is an example of how to read everything the PVS reports with update()
#

import asyncio
import logging
import os

import aiohttp

from pypvs.exceptions import PVSError
from pypvs.pvs import PVS

logging.basicConfig(level=logging.INFO)


async def main():
    host = os.getenv("PVS_HOST")
    if host is None:
        print("Please set the PVS_HOST environment variable with the PVS IP.")
        return

    async with aiohttp.ClientSession() as session:
        pvs = PVS(session=session, host=host, user="ssm_owner")
        try:
            await pvs.setup()
        except PVSError as e:
            logging.error("Cannot communicate with the PVS: %s", e)
            return

        while True:
            data = await pvs.update()
            print(f">>>>>> Gateway: {data.gateway}")
            for kind, devices in (
                ("Inverters", data.inverters),
                ("Meters", data.meters),
                ("ESS", data.ess),
                ("Transfer switches", data.transfer_switches),
            ):
                print(f">>>>>> {kind}:")
                for serial, device in devices.items():
                    print(f"{serial}: {device}")
            await asyncio.sleep(30)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Exiting...")
