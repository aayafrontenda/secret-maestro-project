"""Operational commands: `python -m app.cli <command>`."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.db import dispose_engine, get_session_factory
from app.core.migrations import run_migrations
from app.ml import build_ml_client
from app.services import checklists as checklist_service
from app.services import dialogs as dialog_service
from app.services import evaluations as evaluation_service
from app.services.organizer import fetch_dataset, load_dataset_file


async def cmd_migrate(_: argparse.Namespace) -> None:
    await run_migrations(get_settings().database_url)
    print("migrations applied")


async def cmd_seed(args: argparse.Namespace) -> None:
    settings = get_settings()
    await run_migrations(settings.database_url)
    async with get_session_factory()() as session:
        checklist = await checklist_service.ensure_default_checklist(session)
        await session.commit()
        print(
            f"default checklist: #{checklist.id} '{checklist.name}' "
            f"({len(checklist.criteria)} criteria)"
        )

        if args.file:
            dataset = load_dataset_file(args.file)
            source = "file"
        elif args.group_id:
            if not settings.organizer_api_url:
                sys.exit("ORGANIZER_API_URL is not set")
            dataset = await fetch_dataset(settings.organizer_api_url, args.group_id)
            source = "organizer_api"
        else:
            return
        created, updated, _ = await dialog_service.upsert_dialogs(
            session,
            dataset.records,
            source=source,
            dataset_group_id=dataset.dataset_group_id or args.group_id,
        )
        await session.commit()
        print(f"dialogs: {created} created, {updated} updated (group {dataset.dataset_group_id})")


async def cmd_evaluate_all(args: argparse.Namespace) -> None:
    """Evaluate every dialog in-process (no server needed) and print a summary."""
    settings = get_settings()
    await run_migrations(settings.database_url)
    ml = build_ml_client(settings)
    factory = get_session_factory()
    async with factory() as session:
        checklist = await checklist_service.ensure_default_checklist(session)
        await session.commit()
        dialogs, _, _ = await dialog_service.list_dialogs(session, limit=10_000)
        batch_id, created, skipped = await evaluation_service.create_batch(
            session, dialogs, checklist, skip_evaluated=not args.force
        )
        await session.commit()
        ids = [e.id for e in created]
    print(f"batch {batch_id}: {len(ids)} queued, {skipped} skipped")

    sem = asyncio.Semaphore(settings.queue_workers)

    async def run(ev_id: int) -> None:
        async with sem, factory() as session:
            ev = await evaluation_service.run_evaluation(session, ev_id, ml)
            print(
                f"  {ev.dialog_id:12} {ev.status.value:9} "
                f"total={ev.original_total} grave={ev.grave_error}"
            )

    await asyncio.gather(*(run(i) for i in ids))
    await ml.aclose()


async def cmd_export_checklist(args: argparse.Namespace) -> None:
    await run_migrations(get_settings().database_url)
    async with get_session_factory()() as session:
        checklist = await checklist_service.ensure_default_checklist(session)
        await session.commit()
        data = await checklist_service.snapshot(session, checklist)
    out = Path(args.out) if args.out else None
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if out:
        out.write_text(text, encoding="utf-8")
        print(f"written to {out}")
    else:
        print(text)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="apply database migrations")

    seed = sub.add_parser("seed", help="create the default checklist and import dialogs")
    src = seed.add_mutually_exclusive_group()
    src.add_argument("--file", help="organizer JSON file (e.g. data/dev_dataset.json)")
    src.add_argument("--group-id", help="fetch from ORGANIZER_API_URL with this group_id")

    ev = sub.add_parser("evaluate-all", help="evaluate every dialog with the default checklist")
    ev.add_argument("--force", action="store_true", help="re-evaluate already evaluated dialogs")

    exp = sub.add_parser("export-checklist", help="print the default checklist as JSON")
    exp.add_argument("--out")

    args = parser.parse_args(argv)
    handler = {
        "migrate": cmd_migrate,
        "seed": cmd_seed,
        "evaluate-all": cmd_evaluate_all,
        "export-checklist": cmd_export_checklist,
    }[args.command]

    async def runner() -> None:
        try:
            await handler(args)
        finally:
            await dispose_engine()

    asyncio.run(runner())


if __name__ == "__main__":
    main()
