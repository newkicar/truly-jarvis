import sys
def show(path, start, end):
    with open(path, encoding='utf-8') as f:
        lines = f.readlines()
    print(f"----- {path} L{start}-{end} -----")
    for i, l in enumerate(lines[start-1:end], start=start):
        print(f"{i:5d} {l}", end='')
    print()
for a in sys.argv[1:]:
    path, s, e = a.split(':')
    show(path, int(s), int(e))
