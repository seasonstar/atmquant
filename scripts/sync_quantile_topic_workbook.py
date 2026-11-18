"""同步量化策略开发12到公众号选题库，保留其他单元格与公式。"""
from pathlib import Path

import openpyxl

path = Path("/Users/mac/code/atmquant/articles/公众号选题规划-交易没有那么简单.xlsx")
temporary = path.with_name(".公众号选题规划-交易没有那么简单.syncing.xlsx")
workbook = openpyxl.load_workbook(path, data_only=False)
before = {
    (sheet.title, cell.coordinate): (cell.value, cell.data_type, cell.style_id)
    for sheet in workbook.worksheets
    for row in sheet.iter_rows()
    for cell in row
}
formula_before = {
    key: value[0]
    for key, value in before.items()
    if value[1] == "f"
}

sheet = workbook["选题库"]
matches = [
    row for row in range(2, sheet.max_row + 1)
    if sheet.cell(row, 1).value == "量化策略开发" and str(sheet.cell(row, 2).value) == "12"
]
assert len(matches) == 1, f"第12篇目标行数量异常: {matches}"
row = matches[0]
assert sheet.cell(row, 9).value == "待写", "目标行不是待写状态，停止覆盖"
updates = {
    3: "最坏5%的行情，该下多大仓位？ - 分位数回归动态仓位实验",
    5: "5%收益条件分位数与CAViaR-AS；固定/ATR/历史分位数/EWMA/CAViaR五组仓位对照；12品种双成本回测；未达预登记门槛，负结果结项",
    6: "ML4T + CAViaR-AS + 12个期货主力合约",
    9: "已写",
}
for column, value in updates.items():
    sheet.cell(row, column).value = value
workbook.save(temporary)

reopened = openpyxl.load_workbook(temporary, data_only=False)
after = {
    (sheet.title, cell.coordinate): (cell.value, cell.data_type, cell.style_id)
    for sheet in reopened.worksheets
    for row in sheet.iter_rows()
    for cell in row
}
allowed = {("选题库", reopened["选题库"].cell(row, column).coordinate) for column in updates}
assert before.keys() == after.keys(), "工作簿单元格范围发生变化"
for key in before:
    if key in allowed:
        continue
    assert before[key] == after[key], f"非目标单元格发生变化: {key}"
formula_after = {key: value[0] for key, value in after.items() if value[1] == "f"}
assert formula_before == formula_after, "公式发生变化"
assert after[("选题库", f"I{row}")][0] == "已写"
temporary.replace(path)
print(f"已更新：选题库第 {row} 行")
print([reopened["选题库"].cell(row, column).value for column in range(1, 10)])
print(f"非目标单元格与 {len(formula_before)} 个公式保持不变")
