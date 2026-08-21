#!/usr/bin/env python3
"""Enable the upstream get_table_info tool for the local coordinate workflow."""

from __future__ import annotations

import argparse
from pathlib import Path


INDEX_DISABLED = """// 비활성화: 응답량 과다로 Cursor 초기화 유발
// export {
//   getTableInfo,
//   getTableInfoSchema,
//   type GetTableInfoInput,
// } from './getTableInfo.js';"""

INDEX_ENABLED = """export {
  getTableInfo,
  getTableInfoSchema,
  type GetTableInfoInput,
} from './getTableInfo.js';"""

SERVER_IMPORT_DISABLED = """  // getTableInfo - 응답량이 너무 커서 Cursor 초기화 유발, 비활성화
  // getTableInfoSchema,"""

SERVER_IMPORT_ENABLED = """  getTableInfo,
  getTableInfoSchema,"""

SERVER_TOOL_DISABLED = """  // 7. 통계표 정보 조회 - 비활성화 (응답량 과다로 Cursor 초기화 유발)
  // 대신 quick_stats가 정적 파라미터를 사용하여 동일 기능 제공
  // server.tool(
  //   getTableInfoSchema.name,
  //   getTableInfoSchema.description,
  //   getTableInfoSchema.inputSchema.shape,
  //   async (args) => {
  //     const result = await getTableInfo(args as any);
  //     return {
  //       content: [
  //         {
  //           type: 'text' as const,
  //           text: JSON.stringify(result, null, 2),
  //         },
  //       ],
  //     };
  //   }
  // );"""

SERVER_TOOL_ENABLED = """  // 7. Local coordinate metadata lookup
  server.tool(
    getTableInfoSchema.name,
    getTableInfoSchema.description,
    getTableInfoSchema.inputSchema.shape,
    async (args) => {
      const result = await getTableInfo(args as any);
      return {
        content: [
          {
            type: 'text' as const,
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    }
  );"""


def replace_once(text: str, disabled: str, enabled: str, label: str) -> tuple[str, bool]:
    if enabled in text:
        return text, False
    occurrences = text.count(disabled)
    if occurrences != 1:
        raise RuntimeError(
            f"Upstream MCP layout changed for {label}: expected one disabled block, "
            f"found {occurrences}"
        )
    return text.replace(disabled, enabled, 1), True


def patch_repository(repository: Path) -> bool:
    index_path = repository / "src/tools/index.ts"
    server_path = repository / "src/server.ts"
    if not index_path.is_file() or not server_path.is_file():
        raise FileNotFoundError(f"Not a korea-stats-mcp source checkout: {repository}")

    index_text = index_path.read_text(encoding="utf-8")
    server_text = server_path.read_text(encoding="utf-8")
    index_text, index_changed = replace_once(
        index_text, INDEX_DISABLED, INDEX_ENABLED, "tools/index.ts export"
    )
    server_text, import_changed = replace_once(
        server_text, SERVER_IMPORT_DISABLED, SERVER_IMPORT_ENABLED, "server.ts import"
    )
    server_text, tool_changed = replace_once(
        server_text, SERVER_TOOL_DISABLED, SERVER_TOOL_ENABLED, "server.ts registration"
    )

    if index_changed:
        index_path.write_text(index_text, encoding="utf-8")
    if import_changed or tool_changed:
        server_path.write_text(server_text, encoding="utf-8")

    final_index = index_path.read_text(encoding="utf-8")
    final_server = server_path.read_text(encoding="utf-8")
    required = (
        "getTableInfoSchema" in final_index,
        "getTableInfo," in final_server,
        "server.tool(\n    getTableInfoSchema.name" in final_server,
    )
    if not all(required):
        raise RuntimeError("get_table_info activation verification failed")
    return index_changed or import_changed or tool_changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", type=Path)
    args = parser.parse_args()
    changed = patch_repository(args.repository.resolve())
    print(f"get_table_info enabled; changed={str(changed).lower()}")


if __name__ == "__main__":
    main()
