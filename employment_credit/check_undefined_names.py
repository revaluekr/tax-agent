# -*- coding: utf-8 -*-
"""
[개발자 전용 정적 검증 스크립트] 전체 파이썬 파일 미정의 심볼(NameError 위험) AST·Symtable 전수 검사기
- 앱 실행 중(런타임)이나 `verify_golden_case_invariants()` 내부에서는 호출하지 않으며,
  코드 수정 후 배포 전 개발자가 단독 실행(`python3 check_undefined_names.py`)하여
  누락된 import나 오타로 인한 NameError 가능성을 0건으로 검증합니다.
"""
from __future__ import annotations

import ast
import builtins
import os
import symtable
import sys
from typing import Iterable


BUILTIN_NAMES = set(dir(builtins)) | {
    "__file__",
    "__name__",
    "__doc__",
    "__package__",
    "__spec__",
    "__all__",
    "__annotations__",
}


def _collect_top_level_exports(filepath: str) -> set[str]:
    """`from .mod import *` 해석을 위해 대상 모듈의 최상위 정의 심볼을 수집합니다."""
    if not os.path.isfile(filepath):
        return set()
    with open(filepath, "r", encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src, filename=filepath)
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                for nm in ast.walk(t):
                    if isinstance(nm, ast.Name) and not nm.id.startswith("_"):
                        names.add(nm.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if not node.target.id.startswith("_"):
                names.add(node.target.id)
    return names


def _collect_unbound_load_names_in_file(filepath: str) -> list[tuple[int, str, str]]:
    """
    단일 파이썬 파일의 AST와 symtable을 결합 분석하여,
    모듈 전역·클래스·함수·컴프리헨션·예외 핸들러 어디에서도 정의/import되지 않은 채
    Load 컨텍스트로 참조되는 심볼 목록 `[(lineno, scope_name, symbol_name), ...]`을 반환합니다.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source, filename=filepath)
    st_top = symtable.symtable(source, filepath, "exec")
    cur_dir = os.path.dirname(os.path.abspath(filepath))

    # 모듈 수준에서 정의되거나 import된 심볼 수집
    module_defined: set[str] = set(BUILTIN_NAMES)
    for sym in st_top.get_symbols():
        if sym.is_imported() or sym.is_assigned() or sym.is_namespace():
            module_defined.add(sym.get_name())

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module_defined.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                module_defined.add(bound)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*" and node.module:
                    rel_mod = os.path.join(cur_dir, f"{node.module.split('.')[-1]}.py")
                    module_defined |= _collect_top_level_exports(rel_mod)
                elif alias.name != "*":
                    module_defined.add(alias.asname or alias.name)

    missing: list[tuple[int, str, str]] = []

    def _walk_symtable(tbl: symtable.SymbolTable, enclosing_locals: set[str]) -> dict[tuple[str, int], set[str]]:
        cur_locals = set(enclosing_locals)
        for sym in tbl.get_symbols():
            if sym.is_local() or sym.is_parameter() or sym.is_imported() or sym.is_assigned() or sym.is_namespace():
                cur_locals.add(sym.get_name())
        scope_map: dict[tuple[str, int], set[str]] = {(tbl.get_name(), tbl.get_lineno()): cur_locals}
        for child in tbl.get_children():
            scope_map.update(_walk_symtable(child, cur_locals))
        return scope_map

    scope_locals_map = _walk_symtable(st_top, module_defined)

    def _visit_node(node: ast.AST, scope_name: str, visible_names: set[str], in_annotation: bool = False) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_locals = set(visible_names) | {node.name}
            st_locals = scope_locals_map.get((node.name, node.lineno), set())
            fn_locals |= st_locals
            for arg in (
                list(node.args.posonlyargs)
                + list(node.args.args)
                + list(node.args.kwonlyargs)
                + ([node.args.vararg] if node.args.vararg else [])
                + ([node.args.kwarg] if node.args.kwarg else [])
            ):
                fn_locals.add(arg.arg)
            for dec in node.decorator_list:
                _visit_node(dec, scope_name, visible_names, in_annotation=False)
            for d in list(node.args.defaults) + [x for x in node.args.kw_defaults if x is not None]:
                _visit_node(d, scope_name, visible_names, in_annotation=False)
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
                    fn_locals.add(sub.id)
                elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    fn_locals.add(sub.name)
                elif isinstance(sub, ast.ExceptHandler) and sub.name:
                    fn_locals.add(sub.name)
                elif isinstance(sub, ast.Import):
                    for alias in sub.names:
                        fn_locals.add(alias.asname or alias.name.split(".")[0])
                elif isinstance(sub, ast.ImportFrom):
                    for alias in sub.names:
                        if alias.name != "*":
                            fn_locals.add(alias.asname or alias.name)
            for stmt in node.body:
                _visit_node(stmt, node.name, fn_locals, in_annotation=False)
            return

        if isinstance(node, ast.ClassDef):
            cls_locals = set(visible_names) | {node.name}
            for base in node.bases:
                _visit_node(base, scope_name, visible_names, in_annotation=False)
            for kw in node.keywords:
                _visit_node(kw, scope_name, visible_names, in_annotation=False)
            for dec in node.decorator_list:
                _visit_node(dec, scope_name, visible_names, in_annotation=False)
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    cls_locals.add(sub.name)
                elif isinstance(sub, ast.Assign):
                    for t in sub.targets:
                        for nm in ast.walk(t):
                            if isinstance(nm, ast.Name):
                                cls_locals.add(nm.id)
            for stmt in node.body:
                _visit_node(stmt, node.name, cls_locals, in_annotation=False)
            return

        if isinstance(node, ast.Lambda):
            lam_locals = set(visible_names)
            for arg in (
                list(node.args.posonlyargs)
                + list(node.args.args)
                + list(node.args.kwonlyargs)
                + ([node.args.vararg] if node.args.vararg else [])
                + ([node.args.kwarg] if node.args.kwarg else [])
            ):
                lam_locals.add(arg.arg)
            for d in list(node.args.defaults) + [x for x in node.args.kw_defaults if x is not None]:
                _visit_node(d, scope_name, visible_names, in_annotation=False)
            _visit_node(node.body, f"{scope_name}.<lambda>", lam_locals, in_annotation=in_annotation)
            return

        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            comp_locals = set(visible_names)
            for gen in node.generators:
                _visit_node(gen.iter, scope_name, comp_locals, in_annotation=in_annotation)
                for nm in ast.walk(gen.target):
                    if isinstance(nm, ast.Name) and isinstance(nm.ctx, ast.Store):
                        comp_locals.add(nm.id)
                for if_clause in gen.ifs:
                    _visit_node(if_clause, scope_name, comp_locals, in_annotation=in_annotation)
            if isinstance(node, ast.DictComp):
                _visit_node(node.key, scope_name, comp_locals, in_annotation=in_annotation)
                _visit_node(node.value, scope_name, comp_locals, in_annotation=in_annotation)
            else:
                _visit_node(node.elt, scope_name, comp_locals, in_annotation=in_annotation)
            return

        if isinstance(node, ast.AnnAssign):
            if node.value:
                _visit_node(node.value, scope_name, visible_names, in_annotation=False)
            return

        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if not in_annotation and node.id not in visible_names and node.id not in module_defined:
                missing.append((node.lineno, scope_name, node.id))
            return

        for child in ast.iter_child_nodes(node):
            _visit_node(child, scope_name, visible_names, in_annotation=in_annotation)

    _visit_node(tree, "<module>", module_defined, in_annotation=False)
    return sorted(set(missing), key=lambda x: (x[0], x[2]))


def check_files(filepaths: Iterable[str]) -> tuple[bool, dict[str, list[tuple[int, str, str]]]]:
    results: dict[str, list[tuple[int, str, str]]] = {}
    all_ok = True
    for fp in filepaths:
        miss = _collect_unbound_load_names_in_file(fp)
        results[fp] = miss
        if miss:
            all_ok = False
    return all_ok, results


def main() -> int:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    pkg_dir = os.path.join(base_dir, "employment_credit")
    target_files: list[str] = []
    for root_py in ("app.py", "agent.py", "law_api.py"):
        p = os.path.join(base_dir, root_py)
        if os.path.isfile(p):
            target_files.append(p)
    if os.path.isdir(pkg_dir):
        for fn in sorted(os.listdir(pkg_dir)):
            if fn.endswith(".py"):
                target_files.append(os.path.join(pkg_dir, fn))

    ok, res = check_files(target_files)
    print(f"=== AST Undefined Symbol Check ({len(target_files)} files) ===")
    for fp, miss in res.items():
        rel = os.path.relpath(fp, base_dir)
        if not miss:
            print(f"[PASS] {rel}: 미정의 심볼 0건")
        else:
            print(f"[FAIL] {rel}: 미정의 심볼 {len(miss)}건 발견")
            for lineno, sc, sym in miss:
                print(f"   - line {lineno} (in {sc}): '{sym}' is not defined")
    print("=" * 55)
    print(f"최종 결과: {'ALL PASS (0 undefined names)' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())