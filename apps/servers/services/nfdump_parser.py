import json
from datetime import datetime


class NFDumpParser:

    @staticmethod
    def parse(json_text, target_datetime, port=None):

        data = json.loads(json_text)

        results = []

        for item in data:

            t_first = item.get("t_first")

            if not t_first:
                continue

            flow_time = datetime.fromisoformat(t_first)

            diff = abs((flow_time - target_datetime).total_seconds())

            match_type = "near_match"

            if diff < 60:
                match_type = "exact_match"

            if port:
                p_start = int(item.get("pblock_start"))
                p_end = int(item.get("pblock_end"))

                if not (p_start <= port <= p_end):
                    continue

            results.append(
                {
                    "source_ip": item.get("src4_addr"),
                    "datetime": t_first,
                    "match_type": match_type,
                    "port_block_start": item.get("pblock_start"),
                    "port_block_end": item.get("pblock_end"),
                }
            )

        return results

