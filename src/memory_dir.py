'''dotdir：旧项目级 memory/ 一次性并入 .jarvis/memory，外加全局 copy-seed 播种。

config.py 的 memory_dir 哨兵语义（dotdir 起）：缺省记忆目录 = 项目级 {project_root}/.jarvis/memory。
本模块负责两件事（main.py 在 load_config 之后调用，返回日志行写 stderr；异常只告警不阻塞启动）：
1. 合并旧布局 {project_root}/memory 进 .jarvis/memory：顶层文件/ dream/ 子目录逐文件按
   _merge_file 规则（无目标→move；同名同内容→跳过留源；同名异容→更名 __{project} 落位），
   rag-index/ 目标已存→留原地（索引可重建）、目标无→整目录移；其他子目录留原地仅记日志。
2. copy-seed：全局 ~/.jarvis/memory 非空且目标为空 → 一次性整目录拷贝进 .jarvis/memory
   （全局目录永不修改、永不动）。合并先于播种；目标已有内容则跳过播种。
全程幂等、永不删除目标、永不 raise。
'''
import shutil
from pathlib import Path

from src.project_paths import user_home


def _merge_file(src, dst_dir, project_name, notes, label):
    '''把一个源文件合并进目标目录：目标无 → move；同名同内容 → 跳过留源（幂等）；同名异容 → 换名 __{project_name} 落位。'''
    if not label:
        label = src.name
    dst = dst_dir / src.name
    if not dst.exists():
        shutil.move(str(src), str(dst))
        notes.append('moved ' + label + ' → .jarvis/memory')
        return
    try:
        same = src.read_bytes() == dst.read_bytes()
    except OSError:
        same = False
    if same:
        notes.append('同名同内容 ' + label + '，留原地（幂等）')
        return
    target = dst
    i = 2
    while target.exists():
        if i == 2:
            target = dst.with_name('%s__%s%s' % (dst.stem, project_name, dst.suffix))
        else:
            target = dst.with_name('%s__%s__%d%s' % (dst.stem, project_name, i, dst.suffix))
        i += 1
    shutil.move(str(src), str(target))
    notes.append('同名异容 ' + label + ' → 更名落位 ' + target.name)


def maybe_migrate_memory(config):  # noqa: C901
    '''生效记忆目录为项目级 .jarvis/memory 时，合并旧 {project_root}/memory 并 copy-seed 全局记忆。

    显式配置的目录（memory_dir != .jarvis/memory）不迁移直接返回 []；
    合并与播种均幂等；全局 ~/.jarvis/memory 永不修改。返回日志行（空 = 无需动作）。
    '''
    notes = []
    target = (Path(config.project_root) / '.jarvis' / 'memory').resolve()
    if Path(config.memory_dir).resolve() != target:
        return notes
    source = Path(config.project_root) / 'memory'
    project_name = Path(config.project_root).name
    if source.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        for f in sorted(source.iterdir()):
            if f.is_file():
                _merge_file(f, target, project_name, notes, f.name)
        dream = source / 'dream'
        if dream.is_dir():
            dream_target = target / 'dream'
            dream_target.mkdir(parents=True, exist_ok=True)
            for f in sorted(dream.iterdir()):
                if f.is_file():
                    _merge_file(f, dream_target, project_name, notes, 'dream/' + f.name)
            try:
                dream.rmdir()
            except OSError:
                pass
        rag = source / 'rag-index'
        if rag.is_dir():
            if (target / 'rag-index').is_dir():
                notes.append('rag-index/ 目标已存在，留原地（索引可重建）')
            else:
                shutil.move(str(rag), str(target / 'rag-index'))
                notes.append('moved rag-index/ → .jarvis/memory')
        for f in sorted(source.iterdir()):
            if f.is_dir():
                notes.append('子目录 ' + f.name + '/ 留在项目（不自动迁移）')
        try:
            source.rmdir()
        except OSError:
            pass
    # copy-seed：全局 ~/.jarvis/memory 非空且目标为空 → 一次性整目录拷贝（全局不动）
    global_mem = (user_home() / 'memory').resolve()
    if global_mem.is_dir() and any(global_mem.iterdir()):
        if target.is_dir() and any(target.iterdir()):
            notes.append('copy-seed 跳过：.jarvis/memory 已有内容（全局 ~/.jarvis/memory 不改动）')
        else:
            target.mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(global_mem), str(target), dirs_exist_ok=True)
            notes.append('copy-seed: 全局 ~/.jarvis/memory → .jarvis/memory（一次性拷贝，全局不动）')
    return notes
