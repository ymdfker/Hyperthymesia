"""Single entry point of the packaged executable: agent-memory <command> ...
Commands are added as the corresponding parts are ported (design 27.2)."""
import sys
from . import __version__

COMMANDS = {}   # name -> (callable(argv), one-line help); filled by later steps (serve, hook, write, install, doctor)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print('agent-memory %s\ncommands:' % __version__)
        for n, (_, h) in sorted(COMMANDS.items()): print('  %-10s %s' % (n, h))
        return 0
    if argv[0] in ('-V', '--version'):
        print(__version__); return 0
    if argv[0] not in COMMANDS:
        print('unknown command: %s' % argv[0], file=sys.stderr); return 2
    return COMMANDS[argv[0]][0](argv[1:]) or 0


if __name__ == '__main__':
    sys.exit(main())
