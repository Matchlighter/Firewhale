
import json
from .base import NFTBackend, NftError
from typing import Literal

from nftables import Nftables

nft = Nftables()
nft.set_json_output(True)

class LocalNFTBackend(NFTBackend):
    def cmd(self, cmd, *, throw: bool | Literal["continue"] = True):
        if isinstance(cmd, list):
            if throw == "continue":
                for c in cmd:
                    self.cmd(c, throw=False)
                return

            cmd = { "nftables": cmd }

        if isinstance(cmd, dict):
            if "nftables" not in cmd:
                cmd = { "nftables": [cmd] }
            rc, output, error = nft.json_cmd(cmd)
        else:
            rc, output, error = nft.cmd(cmd)

        if rc != 0 and throw == True:
            raise NftError(error)

        if nft.get_json_output() and isinstance(output, str) and output != "":
            output = json.loads(output)

        if isinstance(output, dict):
            output = output["nftables"]

        return output
