# Sticker Pack Review & Audit Report
**Date:** 2026-06-27
**Type:** Audit Report

This report presents a detailed audit of the Telegram sticker packs configured for the **Affection Ping** automation workflow, following the removal of the `HelloKittyLove` pack and the subsequent allowlist expansion.

---

## ⚙️ Configuration Update: Hello Kitty Removed
As requested, the `HelloKittyLove` sticker pack has been removed from the active list.
* **Windmill Variable updated:** `u/admin/affection_sticker_packs` now contains the 11 active packs.
* **Documentation updated:** Reflected the change in [docs/WORKFLOW_ARCHITECTURE.md](file:///root/docs/WORKFLOW_ARCHITECTURE.md#L2946).
* **Validation:** Verified the change by running the `affection_ping` test suite; all tests passed successfully.

---

## 📊 Sticker Pack Statistics
The table below details how the active sticker sets resolve after filtering against the expanded `_AFFECTIONATE_EMOJIS` allowlist.

| Sticker Pack Name | Pack Title | Total Stickers | Affectionate (Whitelisted) | Excluded Stickers | Selection Probability | Filter Rate |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **Kittylove** | Joojoo&Pishi | 64 | 64 | 0 | **25.91%** | 100.0% |
| **BubuDudu** | Bubu❤️Dudu | 77 | 51 | 26 | **20.65%** | 66.2% |
| **Meow meow** (LoveKitten) | Meow meow | 27 | 22 | 5 | **8.91%** | 81.5% |
| **peachlovesgoma** | PeachyGoma | 38 | 16 | 22 | **6.48%** | 42.1% |
| **BearAndBunny** | Bunny and Bear | 22 | 15 | 7 | **6.07%** | 68.2% |
| **catlove2** | kawaii cat 2 | 37 | 19 | 18 | **7.69%** | 51.4% |
| **PusheenTheCat** | Pusheen the Cat | 64 | 20 | 44 | **8.10%** | 31.3% |
| **LoveDove** | Love Dove | 36 | 13 | 23 | **5.26%** | 36.1% |
| **Cute_couple** | rare couple | 40 | 12 | 28 | **4.86%** | 30.0% |
| **BunnyAndBear** | Bunny and Bear | 16 | 9 | 7 | **3.64%** | 56.3% |
| **PenguinsLove** | Whale | 29 | 6 | 23 | **2.43%** | 20.7% |
| **Total (Active)** | - | **450** | **247** | **203** | **100.0%** | **54.9%** |

> [!NOTE]
> The **Selection Probability** is calculated as `Affectionate / 247` (total active affectionate stickers). Following the allowlist expansion, the total number of whitelisted stickers increased from **215** to **247** (a **15% increase** in overall variety).
> 
> Yields for key packs increased significantly:
> - **PusheenTheCat**: Yield increased from **17.2%** (11 stickers) to **31.3%** (20 stickers).
> - **Cute_couple**: Yield increased from **17.5%** (7 stickers) to **30.0%** (12 stickers).

---

## 🔍 Whitelist Audit & Enhancements
The `_AFFECTIONATE_EMOJIS` whitelist has been updated in [affection_ping.py](file:///root/windmill/u/admin/affection_ping.py#L54-L61) to include plain red hearts, sweet/affectionate items, and positive actions:

1. **Red Heart Variation Fix:** Added `"❤"` to resolve the encoding mismatch from sets that do not use the variation selector (`\u2764\ufe0f`).
2. **Added Emojis:**
   - `"💞"` (Revolving Hearts)
   - `"💝"` (Heart with Ribbon)
   - `"💌"` (Love Letter)
   - `"💋"` (Kiss Mark)
   - `"🌹"` (Rose)
   - `"🌸"` (Cherry Blossom)
   - `"👋"` (Waving Hand - for morning greeting stickers)
   - `"😴"` / `"💤"` (Sleeping - for night/sleepy stickers)
3. **De-duplicated:** Removed the redundant double definition of the `"😌"` emoji.
