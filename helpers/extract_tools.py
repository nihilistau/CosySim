import ast
import os
import re
import sys


def main(source_file, target_file, tool_prefix):
    with open(source_file, "r", encoding="utf-8") as f:
        code = f.read()

    tree = ast.parse(code)

    tools_to_extract = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith(tool_prefix):
            # Check if it has @mcp.tool()
            has_tool_decorator = any(
                isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool"
                for d in node.decorator_list
            )
            if has_tool_decorator:
                tools_to_extract.append(node)

    print(f"Found {len(tools_to_extract)} tools starting with '{tool_prefix}'")

    new_impls = []

    for func in tools_to_extract:
        # Generate the _impl function
        func_name = func.name

        sig_parts = []
        for i, arg in enumerate(func.args.args):
            arg_str = (
                f"{arg.arg}: {ast.unparse(arg.annotation)}"
                if arg.annotation
                else arg.arg
            )

            # Find defaults
            defaults_offset = len(func.args.args) - len(func.args.defaults)
            if i >= defaults_offset:
                default_val = ast.unparse(func.args.defaults[i - defaults_offset])
                arg_str += f" = {default_val}"

            sig_parts.append(arg_str)

        sig_str = ", ".join(sig_parts)
        if sig_str:
            sig_str += ", "

        docstring = ast.get_docstring(func)
        doc_str = f'    """{docstring}"""\n' if docstring else ""

        # Get the body of the try block
        body_lines = []
        has_try = False
        for child in func.body:
            if isinstance(child, ast.Try):
                has_try = True
                for stmt in child.body:
                    body_lines.append(ast.unparse(stmt))
                break

        if not has_try:
            print(f"Skipping {func_name} - no try block")
            continue

        impl_body = "\n    ".join(body_lines)

        if "_get_nexus()" in impl_body:
            impl_body = impl_body.replace("_get_nexus()", "nexus_getter()")
            sig_str += "nexus_getter: Any"
        else:
            if sig_str.endswith(", "):
                sig_str = sig_str[:-2]

        # Fix json.dumps returns
        impl_body = re.sub(
            r"return json\.dumps\((.*?)(?:,\s*default=str)?(?:,\s*indent=\d+)?\)",
            r"return \1",
            impl_body,
        )

        impl_code = f"""@mcp_tool
def {func_name}_impl({sig_str}) -> Any:
{doc_str}    {impl_body}
"""
        new_impls.append(impl_code)

    # ensure target file directory exists
    os.makedirs(os.path.dirname(target_file), exist_ok=True)

    # write imports if new file
    if not os.path.exists(target_file) or os.path.getsize(target_file) == 0:
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(
                "from __future__ import annotations\n\nimport json\nfrom typing import Any, Dict, List, Optional\nfrom pydantic import BaseModel, Field\n\nfrom engine.mcp.decorators import mcp_tool, ToolExecutionError\n\n"
            )

    with open(target_file, "a", encoding="utf-8") as f:
        f.write("\n\n".join(new_impls))

    print(f"Added implementations to {target_file}")


if __name__ == "__main__":
    if len(sys.argv) == 4:
        main(sys.argv[1], sys.argv[3], sys.argv[2])
    else:
        main(
            "engine/mcp/devtools_server.py", "engine/mcp/tools/nexus_tools.py", "nexus_"
        )
