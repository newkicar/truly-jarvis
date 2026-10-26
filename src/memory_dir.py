'''项目级 memory 目录一次性迁移到用户全局目录（javis-global-memory T2）。

config.py 的 memory_dir 哨兵语义之后，生效记忆目录默认为 ~/.jarvis/memory（跨项目复用）。
本模块负责把旧的 {project_root}/memory 合并进全局目录：
永不删除目标、永不 raise、幂等（同名同内容不动作）。
main.py 在 load_config 之后调用，返回日志行写 stderr；异常只告警不阻塞启动。
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
        notes.append('moved ' + label + ' → global')
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


def maybe_migrate_memory(config):
    '''生效记忆目录为全局默认时，把 {project_root}/memory 合并进来，返回日志行（空 = 无需动作）。

    显式配置的目录（非全局默认）不迁移；源 == 目标短路；
    顶层常规文件按 _merge_file 规则合并；dream/ 子目录逐文件同规则；
    rag-index/ 目标已存 → 跳过留原地（索引可增量重建）、目标无 → 整目录移；
    其他子目录原地保留仅记日志；源目录清空后尝试 rmdir（失败忽略）。
    '''
    notes = []
    target = Path(config.memory_dir).resolve()
    global_default = (user_home() / 'memory').resolve()
    if target != global_default:
        return notes
    source = Path(config.project_root) / 'memory'
    if source.resolve() == global_default:
        notes.append('memory 目录已是全局路径，无需迁移')
        return notes
    if not source.is_dir():
        return notes
    target.mkdir(parents=True, exist_ok=True)
    project_name = Path(config.project_root).name
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
            notes.append('moved rag-index/ → global')
    for f in sorted(source.iterdir()):
        if f.is_dir():
            notes.append('子目录 ' + f.name + '/ 留在项目（不自动迁移）')
    try:
        source.rmdir()
    except OSError:
        pass
    return notes

