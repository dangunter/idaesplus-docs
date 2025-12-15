#!/usr/bin/env python
"""
Find modules
"""

import argparse
import csv
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
import sys
from typing import Iterator

logging.basicConfig()
_log = logging.getLogger(__name__)


class ClassDeclError(ValueError):
    pass


class NotUnitModel(ValueError):
    pass


@dataclass
class ModelInfo:
    """Record key information about a unit model"""

    name: str
    base_class: str = ""
    url: str = ""
    description: str = ""


class ParserState:
    searching = 1
    declaration = 2
    mid_class = 3
    docstring = 4
    class_ = 5
    docstring_body = 6
    docstring_end = 7


PROJECT_SOURCE_URL = {
    "idaes": "https://github.com/IDAES/idaes-pse/tree/main/idaes/",
    "watertap": "https://github.com/watertap-org/watertap/tree/main/watertap",
    "prommis": "https://github.com/prommis/prommis/tree/main/src/prommis",
}

re_declaration = re.compile(r"@.*\(\s*[\"'](\w+)")
re_class_parts = re.compile(r"class\s+(?P<class>\w+)\s*\((?P<base_classes>.*?)\)")


def find_models(root: Path, base_url: str) -> Iterator[ModelInfo]:
    for dirpath, _, filenames in os.walk(root):
        if dirpath.endswith("/tests") or dirpath.endswith("_"):
            continue
        for name in filenames:
            if name.endswith(".py"):
                file_path = Path(os.path.join(dirpath, name))
                with file_path.open() as f:
                    rel_file_path = file_path.relative_to(root)
                    for info in find_models_in_file(f):
                        info.url = base_url + str(rel_file_path)
                        yield info


def find_models_in_file(f) -> Iterator[ModelInfo]:
    state = ParserState.searching
    for lineno, line in enumerate(f):
        sline = line.strip()
        try:
            if state == ParserState.searching:
                if sline.startswith("@declare_process_block_class"):
                    m = re_declaration.match(sline)
                    if m is None:
                        # maybe multi-line declaration
                        state = ParserState.declaration
                        declaration = sline
                    else:
                        name = m.group(1)
                        cur_model = ModelInfo(name=name)
                        state = ParserState.class_
            elif state == ParserState.declaration:
                if sline.startswith("class"):
                    # done with declaration
                    m = re_declaration.match(declaration)
                    if m is None:
                        _log.warning(
                            f"Cannot extract name from process block declaration "
                            f"(ends line {lineno}): {declaration}"
                        )
                        state = ParserState.searching
                    else:
                        name = m.group(1)
                        if skip_class(name):
                            state = ParserState.searching
                        else:
                            cur_model = ModelInfo(name=name)
                            if sline.endswith(":"):
                                cur_model.base_class = get_base_class(sline)
                                state = ParserState.docstring
                                docstring_lines = []
                            else:
                                class_stmt = sline
                                state = ParserState.mid_class
                else:
                    # still in declaration
                    declaration = declaration + " " + sline
            elif state == ParserState.class_:
                if sline.startswith("class"):
                    if sline.endswith(":"):
                        class_name = get_base_class(sline)
                        cur_model.base_class = class_name
                        state = ParserState.docstring
                        docstring_lines = []
                    else:
                        class_stmt = sline
                        state = ParserState.mid_class
            elif state == ParserState.mid_class:
                class_stmt = class_stmt + " " + sline
                if sline.endswith(":"):
                    class_name = get_base_class(class_stmt)
                    cur_model.base_class = class_name
                    state = ParserState.docstring
                    docstring_lines = []
            elif state == ParserState.docstring:
                if sline == '"""':
                    state = ParserState.docstring_body
                elif sline.startswith('"""'):
                    if sline.endswith('"""'):
                        docstring_lines.append(sline[3:-3])
                        state = ParserState.docstring_end
                    else:
                        docstring_lines.append(sline[3:])
                        state = ParserState.docstring_body
                elif len(sline) == 0:
                    pass
                else:
                    state = ParserState.docstring_end
            elif state == ParserState.docstring_body:
                if sline.endswith('"""'):
                    docstring_lines.append(sline[3:-3])
                    state = ParserState.docstring_end
                else:
                    docstring_lines.append(sline)
            elif state == ParserState.docstring_end:
                docstring = " ".join(docstring_lines)
                cur_model.description = docstring
                yield cur_model
                state = ParserState.searching
        except NotUnitModel:
            state = ParserState.searching
            continue


def skip_class(name):
    return False
    # for skip_keyword in ("ControlVolume", "Reaction", "Parameter", "Interrogator"):
    #     if skip_keyword in name:
    #         return True
    # return False


def get_base_class(s: str) -> str:
    m = re_class_parts.match(s)
    if m is None:
        raise ClassDeclError(f"Unrecognized class declaration in: {s}")
    parts = m.groupdict()
    for bc in parts["base_classes"].split(","):
        bc = bc.strip()
        if bc.startswith("UnitModel"):
            return bc
        # if bc.endswith("Data"):
        #     return bc
    raise NotUnitModel(f"Cannot find appropriate base class in: {s}")


def export_result(stream, items: Iterator[ModelInfo]):
    writer = csv.writer(stream, quoting=csv.QUOTE_ALL)
    writer.writerow(["name", "type", "url", "description"])
    typ = set()
    for x in items:
        typ = get_type(x.base_class)
        writer.writerow((x.name, typ, x.url, x.description))


def get_type(s):
    if s == "FlowsheetBlockData":
        return "Flowsheet"
    if s == "UnitModelBlockData":
        return "UnitModel"
    if s.endswith("Data"):
        s = s[:-4]
    return s


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("root", help="Root of source code tree")
    p.add_argument(
        "--project",
        type=str,
        choices=["idaes", "watertap", "prommis"],
        help="Project name (idaes)",
        default="idaes",
    )
    args = p.parse_args()
    project_url = PROJECT_SOURCE_URL[args.project]
    export_result(sys.stdout, find_models(root=args.root, base_url=project_url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
