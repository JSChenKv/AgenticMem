import argparse
import json
import shutil
from datetime import datetime, timezone

from lab.core import Lab, ROOT, valid_name


def main():
    parser = argparse.ArgumentParser(description='Local Mem0 research agent')
    parser.add_argument('--experiment', default='default')
    parser.add_argument('--user', default='researcher')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('chat')
    ask = commands.add_parser('ask')
    ask.add_argument('text')
    ask.add_argument('--mode', choices=['read', 'write', 'none'], default='read')
    remember = commands.add_parser('remember')
    remember.add_argument('text')
    ingest = commands.add_parser('ingest')
    ingest.add_argument('document', help='.txt path relative to fixtures/')
    commands.add_parser('list')
    search = commands.add_parser('search')
    search.add_argument('text')
    clone = commands.add_parser('clone', help='Clone a CLOSED experiment including Qdrant, history and traces')
    clone.add_argument('destination')
    args = parser.parse_args()
    if args.command == 'clone':
        source = ROOT / 'data' / 'experiments' / valid_name(args.experiment)
        target = ROOT / 'data' / 'experiments' / valid_name(args.destination)
        if not source.is_dir() or target.exists():
            parser.error('Source must exist and destination must be new. Stop all processes using the source first.')
        # Acquire the same exclusive lock as Qdrant before copying a closed database.
        import portalocker
        with (source / 'qdrant' / '.lock').open('a+b') as lock:
            portalocker.lock(lock, portalocker.LOCK_EX | portalocker.LOCK_NB)
            shutil.copytree(source, target, ignore=shutil.ignore_patterns('.lock'))
        # Paths and experiment name are regenerated; retain the parent's manifest as evidence.
        (target / 'manifest.json').rename(target / 'parent-manifest.json')
        (target / 'lineage.json').write_text(json.dumps({'parent': args.experiment, 'cloned_utc': datetime.now(timezone.utc).isoformat()}), encoding='utf-8')
        print(target)
        return
    lab = Lab(args.experiment)
    try:
        if args.command == 'ask':
            result = lab.ask(args.user, args.text, args.mode)
        elif args.command == 'remember':
            result = lab.add(args.user, [{'role': 'user', 'content': args.text}])
        elif args.command == 'ingest':
            result = lab.ingest_document(args.user, args.document)
        elif args.command == 'list':
            result = lab.memories(args.user)
        elif args.command == 'search':
            result = lab.search(args.user, args.text)
        else:
            history = []
            print('Local agent. /new clears chat context; /exit quits. User facts are saved by Mem0.')
            while True:
                try:
                    query = input('You> ').strip()
                except EOFError:
                    break
                if query == '/exit':
                    break
                if query == '/new':
                    history.clear()
                    print('New session; persistent memories retained.')
                    continue
                if not query:
                    continue
                response = lab.ask(args.user, query, mode='write', history=history[-8:])
                print(response['answer'])
                history.extend([{'role': 'user', 'content': query}, {'role': 'assistant', 'content': response['answer']}])
            return
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        lab.close()


if __name__ == '__main__':
    main()
