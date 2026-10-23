"""
Daily Lead Exporter Engine
Selects Top 50 balanced leads across 5 interest categories and exports formatted OpenPyXL workbook
with RTL Arabic layout, freeze panes, hyperlinks, and UTF-8-SIG CSV.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from src.stage2_scrapers.models import ScoredLead

logger = logging.getLogger(__name__)

CATEGORY_TAB_NAMES = {
    "1_Options_Traders": "Options_Traders",
    "2_Halal_Sharia_Stocks": "Halal_Sharia_Stocks",
    "3_Active_Day_Swing_Traders": "Day_Swing_Traders",
    "4_Specific_Tech_Tickers": "Tech_Tickers",
    "5_Broker_Platform_Seekers": "Broker_Seekers",
}

COLUMNS = [
    ("الرقم", 8),
    ("المنصة", 12),
    ("اسم المستخدم", 20),
    ("الاسم المعروض", 24),
    ("رقم الجوال", 20),
    ("رابط واتساب", 22),
    ("حساب تيليجرام", 22),
    ("رابط الملف الشخصي", 24),
    ("الموقع الجغرافي", 20),
    ("تصنيف الاهتمام", 26),
    ("الدرجة الإجمالية (100)", 22),
    ("درجة السلوك الحتمي (60)", 22),
    ("درجة نية الشراء (40)", 22),
    ("المراسلة المباشرة (DM)", 20),
    ("سبب التأهيل والملاحظات", 45),
    ("أبرز المنشورات / التغريدات", 50),
    ("رابط المنشور", 24),
    ("تاريخ الاكتشاف", 18),
]


class LeadExporter:
    def __init__(self, exports_dir: Path | str, target_count: int = 50, min_score: float = 55.0):
        self.exports_dir = Path(exports_dir)
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        self.target_count = target_count
        self.min_score = min_score

    def select_top_leads(self, scored_leads: List[ScoredLead]) -> List[ScoredLead]:
        """
        Filters and selects up to target_count (default 50) leads,
        ensuring a balanced distribution across the 5 interest categories.
        """
        # 1. Filter out disqualified leads and those below min score
        valid_leads = [
            sl for sl in scored_leads
            if sl.total_score >= self.min_score
            and sl.is_genuine_retail_investor
            and not sl.is_competitor_or_seller
        ]

        if not valid_leads:
            logger.warning("No leads met the minimum qualification score.")
            return []

        # Sort all valid leads: phone/whatsapp leads first, then by descending total score
        valid_leads.sort(
            key=lambda x: (
                1 if (x.lead.phone_number or x.lead.whatsapp_url) else 0,
                x.total_score,
            ),
            reverse=True,
        )

        # Group by category
        category_pools: Dict[str, List[ScoredLead]] = {cat: [] for cat in CATEGORY_TAB_NAMES.keys()}
        for sl in valid_leads:
            cat = sl.interest_category if sl.interest_category in category_pools else "5_Broker_Platform_Seekers"
            category_pools[cat].append(sl)

        # Balanced selection: round-robin or quota per category
        selected_leads: List[ScoredLead] = []
        selected_ids = set()

        # Target ~10 leads per category first (within category, phone leads come first due to previous sort)
        quota_per_cat = max(1, self.target_count // len(category_pools))
        for cat, pool in category_pools.items():
            for sl in pool[:quota_per_cat]:
                selected_leads.append(sl)
                selected_ids.add((sl.lead.platform, sl.lead.user_id))

        # Fill remaining slots with the highest remaining scoring leads (phone leads prioritized)
        for sl in valid_leads:
            if len(selected_leads) >= self.target_count:
                break
            key = (sl.lead.platform, sl.lead.user_id)
            if key not in selected_ids:
                selected_leads.append(sl)
                selected_ids.add(key)

        # Final sort: phone leads at the top, then interest category and total score
        selected_leads.sort(
            key=lambda x: (
                0 if (x.lead.phone_number or x.lead.whatsapp_url) else 1,
                x.interest_category,
                -x.total_score,
            )
        )
        logger.info(f"Selected {len(selected_leads)} top balanced leads for export")
        return selected_leads

    def export_excel(self, leads: List[ScoredLead], date_tag: str) -> Path:
        """
        Builds a multi-tab OpenPyXL workbook with RTL Arabic layout,
        header styling, freeze panes, auto column widths, and hyperlinks.
        """
        output_path = self.exports_dir / f"ksa_us_stock_leads_{date_tag}.xlsx"
        wb = openpyxl.Workbook()
        # Remove default sheet
        wb.remove(wb.active)

        # Style definitions
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1B365D", end_color="1B365D", fill_type="solid")
        zebra_fill = PatternFill(start_color="F7F9FC", end_color="F7F9FC", fill_type="solid")
        high_score_fill = PatternFill(start_color="E8F5E9", end_color="E8F5E9", fill_type="solid")
        mid_score_fill = PatternFill(start_color="E3F2FD", end_color="E3F2FD", fill_type="solid")
        link_font = Font(name="Calibri", size=10, color="0000FF", underline="single")
        regular_font = Font(name="Calibri", size=10)
        border_side = Side(style="thin", color="D0D7DE")
        cell_border = Border(left=border_side, right=border_side, top=border_side, bottom=border_side)
        center_align = Alignment(horizontal="center", vertical="center", wrap_text=False)
        right_align = Alignment(horizontal="right", vertical="center", wrap_text=True)

        phone_fill = PatternFill(start_color="D1E7DD", end_color="D1E7DD", fill_type="solid")
        phone_font = Font(name="Calibri", size=10, bold=True, color="0F5132")
        wa_link_font = Font(name="Calibri", size=10, bold=True, color="0F5132", underline="single")

        def populate_sheet(ws: openpyxl.worksheet.worksheet.Worksheet, sheet_leads: List[ScoredLead]) -> None:
            # Enable Right-to-Left (RTL) mode for Arabic
            ws.views.sheetView[0].rightToLeft = True

            # Write headers
            for col_idx, (col_title, _) in enumerate(COLUMNS, start=1):
                cell = ws.cell(row=1, column=col_idx, value=col_title)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = center_align
                cell.border = cell_border
            ws.row_dimensions[1].height = 28

            # Write lead rows
            for row_idx, sl in enumerate(sheet_leads, start=2):
                lead = sl.lead
                primary_trigger = lead.triggers[0] if lead.triggers else None
                trigger_text = primary_trigger.content if primary_trigger else ""
                trigger_url = primary_trigger.url if primary_trigger else ""
                dm_status = "نعم (متاح)" if lead.can_dm is True else ("غير متاح" if lead.can_dm is False else "غير محدد")

                phone_display = lead.phone_number or "غير متوفر"
                wa_display = lead.whatsapp_url or "غير متوفر"
                tg_display = lead.telegram_handle or "غير متوفر"

                row_values = [
                    row_idx - 1,
                    lead.platform.upper(),
                    f"@{lead.username}",
                    lead.display_name,
                    phone_display,
                    wa_display,
                    tg_display,
                    lead.profile_url,
                    lead.location or "غير محدد",
                    sl.interest_category,
                    round(sl.total_score, 1),
                    round(sl.heuristic_score, 1),
                    round(sl.llm_intent_score, 1),
                    dm_status,
                    sl.qualification_reason_ar,
                    trigger_text,
                    trigger_url,
                    lead.first_discovered_at[:10],
                ]

                # Determine row background fill
                fill = None
                if sl.total_score >= 75.0:
                    fill = high_score_fill
                elif sl.total_score >= 60.0:
                    fill = mid_score_fill
                elif row_idx % 2 == 0:
                    fill = zebra_fill

                for col_idx, val in enumerate(row_values, start=1):
                    cell = ws.cell(row=row_idx, column=col_idx)
                    cell.border = cell_border
                    if fill:
                        cell.fill = fill

                    # Format phone number badge
                    if col_idx == 5 and lead.phone_number:
                        cell.value = val
                        cell.font = phone_font
                        cell.fill = phone_fill
                        cell.alignment = center_align
                    # Format WhatsApp hyperlink
                    elif col_idx == 6 and str(val).startswith("http"):
                        cell.value = "محادثة واتساب 💬"
                        cell.hyperlink = str(val)
                        cell.font = wa_link_font
                        cell.fill = phone_fill
                        cell.alignment = center_align
                    # Format Profile hyperlink
                    elif col_idx == 8 and str(val).startswith("http"):
                        cell.value = "رابط الحساب"
                        cell.hyperlink = str(val)
                        cell.font = link_font
                        cell.alignment = center_align
                    # Format Post hyperlink
                    elif col_idx == 17 and str(val).startswith("http"):
                        cell.value = "رابط المنشور"
                        cell.hyperlink = str(val)
                        cell.font = link_font
                        cell.alignment = center_align
                    else:
                        cell.value = val
                        cell.font = regular_font
                        if col_idx in (1, 2, 5, 6, 7, 8, 11, 12, 13, 14, 17, 18):
                            cell.alignment = center_align
                        else:
                            cell.alignment = right_align

                ws.row_dimensions[row_idx].height = 24

            # Freeze panes at A2
            ws.freeze_panes = "A2"

            # Set column widths
            for col_idx, (_, width) in enumerate(COLUMNS, start=1):
                col_letter = get_column_letter(col_idx)
                ws.column_dimensions[col_letter].width = width

        # 1. Master Tab: All_Top_50
        ws_all = wb.create_sheet(title="All_Top_50")
        populate_sheet(ws_all, leads)

        # 2. Five Category Tabs
        for cat_key, tab_name in CATEGORY_TAB_NAMES.items():
            cat_leads = [sl for sl in leads if sl.interest_category == cat_key]
            ws_cat = wb.create_sheet(title=tab_name)
            populate_sheet(ws_cat, cat_leads)

        wb.save(output_path)
        logger.info(f"Successfully generated multi-tab Excel workbook at {output_path}")
        return output_path

    def export_csv(self, leads: List[ScoredLead], date_tag: str) -> Path:
        """
        Exports a flat CSV encoded strictly with utf-8-sig (UTF-8 with BOM)
        to ensure seamless Arabic display in Microsoft Excel.
        """
        output_path = self.exports_dir / f"ksa_us_stock_leads_{date_tag}.csv"
        headers = [c[0] for c in COLUMNS]

        with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            for idx, sl in enumerate(leads, start=1):
                lead = sl.lead
                primary_trigger = lead.triggers[0] if lead.triggers else None
                trigger_text = primary_trigger.content if primary_trigger else ""
                trigger_url = primary_trigger.url if primary_trigger else ""
                dm_status = "نعم (متاح)" if lead.can_dm is True else ("غير متاح" if lead.can_dm is False else "غير محدد")

                row = [
                    idx,
                    lead.platform.upper(),
                    f"@{lead.username}",
                    lead.display_name,
                    lead.phone_number or "غير متوفر",
                    lead.whatsapp_url or "غير متوفر",
                    lead.telegram_handle or "غير متوفر",
                    lead.profile_url,
                    lead.location or "غير محدد",
                    sl.interest_category,
                    round(sl.total_score, 1),
                    round(sl.heuristic_score, 1),
                    round(sl.llm_intent_score, 1),
                    dm_status,
                    sl.qualification_reason_ar,
                    trigger_text.replace("\n", " "),
                    trigger_url,
                    lead.first_discovered_at[:10],
                ]
                writer.writerow(row)

        logger.info(f"Successfully generated UTF-8 BOM CSV at {output_path}")
        return output_path
        return output_path

    def export_all(self, scored_leads: List[ScoredLead], date_tag: Optional[str] = None) -> Dict[str, Path]:
        """
        Orchestrates selection of Top 50 and generation of both Excel and CSV export files.
        """
        date_str = date_tag or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        top_leads = self.select_top_leads(scored_leads)

        excel_path = self.export_excel(top_leads, date_tag=date_str)
        csv_path = self.export_csv(top_leads, date_tag=date_str)

        if not excel_path.exists() or excel_path.stat().st_size == 0:
            raise RuntimeError(f"Excel export failed or produced 0-byte file: {excel_path}")
        if not csv_path.exists() or csv_path.stat().st_size == 0:
            raise RuntimeError(f"CSV export failed or produced 0-byte file: {csv_path}")

        return {
            "excel": excel_path,
            "csv": csv_path,
            "leads_exported": top_leads,
        }
