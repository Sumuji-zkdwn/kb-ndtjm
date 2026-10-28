"""Download public environments through the SDK, without inspecting game source."""
import argparse
import logging
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("games", nargs="+", default=["ls20", "ft09", "vc33"])
    args = parser.parse_args()
    os.environ.setdefault("MPLCONFIGDIR", str(Path(".cache/mpl").resolve()))
    os.environ.setdefault("XDG_CACHE_HOME", str(Path(".cache").resolve()))
    from arc_agi import Arcade, OperationMode
    logger = logging.getLogger("arc3.download")
    logger.setLevel(logging.ERROR)
    logging.getLogger("arc_agi.scorecard").setLevel(logging.ERROR)
    arc = Arcade(operation_mode=OperationMode.NORMAL, logger=logger)
    try:
        for game in args.games:
            env = arc.make(game)
            if env is None:
                raise RuntimeError(f"Could not download {game}")
            print(env.info.game_id)
    finally:
        arc.close_scorecard()


if __name__ == "__main__":
    main()
