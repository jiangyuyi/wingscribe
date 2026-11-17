"""Sparse subtree selection. No directory listing is needed to resolve a rule."""
import os
from pathlib import Path


def _path(value):
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        raise ValueError('目录路径不能为空')
    return Path(os.path.abspath(os.path.normpath(value)))


def _key(path):
    return tuple(os.path.normcase(part) for part in path.parts)


def _within(child, parent, *, strict=False):
    return child[:len(parent)] == parent and (not strict or len(child) > len(parent))


class FolderSelection:
    def __init__(self, paths, excluded_paths=(), *, recursive=True):
        self.recursive = recursive
        positive = {_key(_path(value)): _path(value) for value in paths}
        negative = {_key(_path(value)): _path(value) for value in (excluded_paths or ())}
        if negative and not recursive:
            raise ValueError('排除子目录仅适用于包含子文件夹模式')
        if positive.keys() & negative.keys():
            raise ValueError('同一目录不能同时包含和排除')
        if any(not any(_within(key, root, strict=True) for root in positive) for key in negative):
            raise ValueError('排除目录必须位于已选目录内部')
        rules = {}
        for key in sorted(positive.keys() | negative.keys(), key=lambda value: (len(value), value)):
            included = key in positive
            ancestor = next((rules[parent][1] for parent in sorted(rules, key=len, reverse=True)
                             if _within(key, parent, strict=True)), False)
            # Nonrecursive selection has no inheritance or subtree compaction.
            if not recursive or included != ancestor:
                rules[key] = ((positive if included else negative)[key], included)
        self._rules = rules
        self._ordered_keys = tuple(sorted(rules, key=len, reverse=True))
        self.paths = [str(path) for path, include in rules.values() if include]
        self.excluded_paths = [str(path) for path, include in rules.values() if not include]

    def includes(self, value):
        key = _key(_path(value))
        for root in self._ordered_keys:
            if key == root or self.recursive and _within(key, root):
                return self._rules[root][1]
        return False
