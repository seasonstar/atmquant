"""只读检查公众号选题工作簿，不保存。"""
from pathlib import Path
from zipfile import ZipFile

import openpyxl

path = Path("/Users/mac/code/atmquant/articles/公众号选题规划-交易没有那么简单.xlsx")
with ZipFile(path) as archive:
    names = archive.namelist()
    features = [name for name in names if any(key in name for key in ["drawing", "chart", "media", "pivot", "externalLink", "comments", "vmlDrawing"])]
print("文件大小:", path.stat().st_size)
print("富文本/嵌入部件:", features)

workbook = openpyxl.load_workbook(path, data_only=False, read_only=False)
cached = openpyxl.load_workbook(path, data_only=True, read_only=False)
print("工作表:", workbook.sheetnames)
for sheet in workbook.worksheets:
    formulas = [cell.coordinate for row in sheet.iter_rows() for cell in row if cell.data_type == "f"]
    missing_cache = [coordinate for coordinate in formulas if cached[sheet.title][coordinate].value is None]
    print(f"\n[{sheet.title}] {sheet.max_row}行×{sheet.max_column}列，公式{len(formulas)}，缺缓存{len(missing_cache)}，图表{len(sheet._charts)}，图片{len(sheet._images)}，合并{len(sheet.merged_cells.ranges)}")
    for row in sheet.iter_rows():
        values = [cell.value for cell in row]
        joined = " | ".join("" if value is None else str(value) for value in values)
        if any(keyword in joined for keyword in ["分位数", "贝叶斯", "弹性网", "系列", "状态"]):
            print(row[0].row, values)
