#!/usr/bin/env python3
"""
Build the SYNTHETIC past-request library for the public repository:  data/synthetic/past_requests/

    python tools/make_synthetic_library.py

Every request here is INVENTED for the course. It reproduces the *patterns* found in a private library of real past
lab requests (which test types are asked for, what good requests state, what they typically leave out) without
carrying over any real text, name, customer, program, internal document number, product name, part number, lot,
date or result. Part numbers use the SYN- prefix, sites and business units are BU-A/SITE-A, customers are
"Customer A/B", internal specifications are SYN-GS-xxxx. Public test standards (EIA-364, ASTM, IEC, IPC) are cited
because they are public documents.

Each record gets the same quality check as the form (assistant/quality.py) as of its request date, so the library
shows what the check would have flagged. Run it again after changing the check; the output is deterministic.
"""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "synthetic" / "past_requests"
NOTICE = ("SYNTHETIC: invented for the CMU/Emeritus capstone. Not a real request; no real names, customers, programs, "
          "part numbers, lots, documents or results.")


def sample(name, pn="", lot="", base="", plating="", lube="", housing="", qty=""):
    return {"productName": name, "partNumberRevision": pn, "traceabilityMfgLotInfo": lot, "contactBaseMaterial": base,
            "contactPlating": plating, "contactLubricant": lube, "housingMaterial": housing, "quantity": str(qty)}


def req(n, date, title, tests, samples, spec="", rev="", info="", kind="good", why=(), gaps=(), status="Production",
        project="New Product Development", fmt="Data and Observations", due="", dispo="Send back to requestor",
        conf="yes", sub="no", bu="BU-A", site="SITE-A", legacy="Product/Process Development"):
    return {"n": n, "date": date, "title": title, "kind": kind, "why_good": list(why), "gaps": list(gaps),
            "fields": {"businessUnit": bu, "mFGSite": site, "resultsFormat": fmt, "requestedTestingCompletionDate": due,
                       "testSite": "Lab A", "testSampleStatus": status, "projectType": project,
                       "step2_rows": samples, "postTestingSampleDisposition": dispo,
                       "step3_rows": [{"testsToBePerformed": tests, "applicableSpecifications": spec, "specificationRevision": rev}],
                       "confidentialTestsOrSamples": conf, "canTestingBeSubcontracted": sub, "additionalInformation": info,
                       "sendCopiesTo": ""},
            "legacy_test_type": legacy}


CU = "Copper alloy"
AUNI = "Au over Ni"
LIBRARY = [
    req(1, "2025-01-14", "Temperature rise, parallel-board fixture", "Temperature rise on the 2 samples supplied. Increase current in steps until a 30 °C rise. Two thermocouples per sample, one on each side of the contact array. Record voltage at each step. Expected current 2-3 A.",
        [sample("Synthetic power connector", "SYN-40101 Rev A", "Prototype build", CU, AUNI, "None", "High-temperature nylon", 2)],
        info="Parallel-board version of the series-board test in SYN-LR-PRIOR-01. One test per sample. Each sample is assembled with 2 press-fit pins and 8 screws; tape covers the middle screw holes to prevent shorting.",
        why=["Points to the earlier test and says what is different this time.", "Gives the stopping point (30 °C rise) and the thermocouple locations.",
             "States the expected current, so the lab can choose the supply and range in advance."],
        gaps=["No standard cited for temperature rise (EIA-364-70 is the usual method).", "No lot; ambient and airflow not stated."], status="Prototype"),
    req(2, "2025-02-03", "Contact resistance and mating force, immersed in coolant", "All tests with the samples immersed in the specified coolant. Low-level contact resistance of each beam (4-wire). Mating and unmating force during 20 cycles, then 30 more cycles.",
        [sample("Synthetic busbar clip", "SYN-40202 Rev B", "Lot SYN-L2501", CU, "Ag", "None", "", 4)],
        spec="SYN-GS-1100; EIA-364-23; EIA-364-13; EIA-364-09", rev="SYN-GS-1100 Rev C",
        info="Sample count depends on how many busbar sections can be machined; the goal is 3 to 5, one busbar per sample.",
        why=["States the test medium for every test.", "Cites a standard for each measurement.", "Explains why the sample count may change."],
        gaps=["No acceptance limits for resistance or force.", "Housing material blank."], project="Operational Support", legacy="Customer Specific Testing"),
    req(3, "2025-02-20", "Chlorine exposure and SEM, same day", "Chlorine test and SEM evaluation.",
        [sample("Synthetic high-speed connector", "", "", "", "Au over Ni, 0.76 µm on mating area", "", "", 3)],
        info="The chlorine test needs to be finished today; SEM can wait.", kind="contrast",
        why=["Gives the plating thickness on the mating area.", "Says which part is urgent."],
        gaps=["Asks for results the same day.", "No method or exposure conditions, and no SEM question.", "No part number, lot or disposition."], dispo=""),
    req(4, "2025-03-11", "Mixed flowing gas, unmated and mated groups", "Mixed flowing gas exposure. Group 1 (3 samples): 7 days unmated, LLCR, then 7 days mated. Group 2 (3 samples): 7 days mated, LLCR, then 7 days mated. LLCR before and after each exposure.",
        [sample("Synthetic I/O connector, unmated group", "SYN-40303 Rev A", "Lot SYN-L2503", CU, "Au over Ni", "None", "LCP", 3),
         sample("Synthetic I/O connector, mated group", "SYN-40303 Rev A", "Lot SYN-L2503", CU, "Au over Ni", "None", "LCP", 3)],
        spec="EIA-364-65", rev="EIA-364-65 Rev B", info="Objective: confirm the new plating line matches the current line before release.",
        why=["Two groups that differ only in mating state, with the sequence for each.", "Cites the method; states the objective."],
        gaps=["No LLCR change limit.", "Exposure class not stated."], status="Pre-Production", legacy="Product/Process Qualification"),
    req(5, "2025-03-25", "Full qualification with annotated test board", "Full qualification per the attached product specification tables (test groups and sequences).",
        [sample("Synthetic mezzanine connector", "SYN-40404 Rev C", "", CU, AUNI, "None", "LCP", 28)],
        spec="EIA-364-1000", rev="", info="A photo of the LLCR test board marks the screw torque (12 ± 2 N·cm) so every assembly is done the same way.",
        why=["Complete part data and quantity.", "Cites the qualification standard.", "Shows the assembly torque on a photo of the test board."],
        gaps=["Test groups only in an attachment.", "No lot; no revision for the standard.", "Objective not stated."], fmt="Formal Report (Internal)", legacy="Product/Process Qualification"),
    req(6, "2025-04-08", "Competitor plating thickness by cross-section", "Cross-section each terminal at the pin and measure the gold plating thickness. Do our parts first.",
        [sample("Competitor receptacle", "Competitor part (as marked)", "", "", "", "", "", 1), sample("Competitor header", "Competitor part (as marked)", "", "", "", "", "", 1),
         sample("Synthetic receptacle", "SYN-40505 Rev A", "Lot SYN-L2507", CU, AUNI, "", "LCP", 1), sample("Synthetic header", "SYN-40506 Rev A", "Lot SYN-L2507", CU, AUNI, "", "LCP", 1)],
        why=["Compares like with like (receptacle and header from both sources).", "Says what to measure and where, and the order of work."],
        gaps=["No method or number of readings.", "Results format and disposition blank."], status="Competitor", fmt="", dispo=""),
    req(7, "2025-04-22", "Hardness: certificate vs specification", "Measure the hardness of the base metal.",
        [sample("Synthetic power blade", "SYN-40606 Rev A", "", "Stainless 301", "None", "", "", 1)],
        info="The material specification calls for Rockwell C34; the supplier certificate gives HV 340. Please verify.",
        why=["Asks one clear question with both numbers.", "Small scope that fits a short turnaround."],
        gaps=["No lot.", "Hardness method and load not stated (Rockwell or microhardness on thin strip)."]),
    req(8, "2025-05-06", "Temperature rise, two current setups", "Setup 1, signals and power: signals at 0.25 A, ramp power to over 2 A or a 40 °C rise, then ramp signals to 0.5 A. Setup 2, signals, power and grounds: same, with grounds ramped with power.",
        [sample("Synthetic pluggable connector, fast", "SYN-40707 Rev A", "", "", "", "", "", 1), sample("Synthetic pluggable connector, standard", "SYN-40708 Rev A", "", "", "", "", "", 1)],
        info="New test boards are on order; expected next week.",
        why=["Two setups with the current plan for each.", "Warns that the test boards are not here yet."],
        gaps=["No standard cited.", "No thermocouple locations or ambient."], conf="", sub=""),
    req(9, "2025-05-20", "Cap insertion and removal, per-sample cycles", "Cap insertion and removal force: 5 more cycles on samples 3, 4 and 5; 10 more cycles on samples 1 and 2.",
        [sample("Synthetic socket with cap", "SYN-40808 Rev 17 (cap SYN-40809 Rev 12)", "", "", "", "N/A", "N/A", 5)],
        why=["Cycle plan per sample.", "Revisions for the socket and its cap."],
        gaps=["No force limit or speed.", "The earlier cycles are not referenced."], status="Prototype"),
    req(10, "2025-06-03", "CT scan, five sample groups", "CT scan, one sample per group, both ends of each sample.",
        [sample("Synthetic cable leg, new revision", "SYN-40909 Rev B", "Line 2, May 2025", "C52100", "Au 0.76 µm", "None", "LCP", 1),
         sample("Synthetic cable leg, new revision with dimple", "SYN-40909 Rev B", "Line 2, May 2025", "C52100", "Au 0.76 µm", "None", "LCP", 1),
         sample("Synthetic cable leg, after testing", "SYN-40909 Rev B", "Line 2, May 2025", "C52100", "Au 0.76 µm", "None", "LCP", 1)],
        info="Drawing marks the feature of interest.",
        why=["Complete material data and a lot for every group.", "Named groups and a drawing of the feature."],
        gaps=["Does not say what to measure from the scan.", "Groups share one part number; samples must be labelled."], status="Pre-Production"),
    req(11, "2025-06-17", "Lubricant change verification", "Run test groups 2, 3b and 5 of the product specification on both connector styles.",
        [sample("Synthetic power connector, right angle", "SYN-41010 Rev A", "Lot SYN-L2511", "Signal: C51000; power: C18070", "Signal: Au flash; power: Au", "Power pins: lubricant B", "PA9T", 15),
         sample("Synthetic power connector, vertical", "SYN-41011 Rev A", "Lot SYN-L2511", "Signal: C70250; power: C18070", "Signal: Au flash; power: Au", "Power pins: lubricant B", "PA9T", 15)],
        spec="SYN-GS-1314", rev="SYN-GS-1314 Rev A",
        info="Objective: verify that changing the lubricant does not affect performance. Unsoldered samples go to groups 2 and 3b (signal LLCR, shock and vibration can be skipped); soldered samples go to the temperature-rise group.",
        why=["States the objective.", "Cites the governing specification with its revision.", "Materials per contact type, and which samples suit which group and why."],
        gaps=["Test matrix only in an annex."], fmt="Formal Report (Customer)", legacy="Product/Process Development"),
    req(12, "2025-07-01", "End-of-life program for a customer", "Custom end-of-life: group 2A (5 years at 65 °C), group 2B (7 years), group 2C (10 years), and group 3.",
        [sample("Synthetic edge connector", "SYN-41212 Rev A", "Lot SYN-L2513", CU, "0.76 µm Au over 1.27 µm Ni", "N/A", "PA9T", 25),
         sample("Host test board", "SYN-41213 Rev A", "", "", "", "", "FR-4", 25)],
        spec="EIA-364-1004", rev="", info="Customer A purchase order received; test plan Rev 1. Custom boards are needed to apply current during vibration.",
        why=["Full traceability and plating thickness.", "Test groups with simulated life.", "Ties to the customer plan and warns about custom boards."],
        gaps=["Group 3 not described; plan not in the record."], fmt="Formal Report (Customer)", dispo="Keep in the lab", project="Operational Support", legacy="Customer Specific Testing"),
    req(13, "2025-07-15", "Cable durability with two speed profiles", "Durability and mate/unmate: 6 samples at 25.4 mm/min for all 200 cycles; 6 samples at 25.4 mm/min for 5 cycles then 127 mm/min for 195 cycles. Separate cables for plating thickness, porosity and wire pull.",
        [sample("Synthetic cable, 26 AWG male", "", "", "C52100", AUNI, "None", "PA66", 15), sample("Synthetic cable, 27 AWG female", "", "", "C52100", AUNI, "None", "PA66", 21)],
        info="Pairs: 26 AWG male with 27 AWG female, 12 pairs.",
        why=["Defines the mating pairs.", "Two speed profiles with sample counts.", "Separate samples for each destructive test."],
        gaps=["No part numbers or lots.", "No standards or limits."], fmt="Formal Report (Customer)", legacy="Product/Process Qualification"),
    req(14, "2025-08-05", "Foam compression method", "Force at 30% strain at 50 mm/min (about 6 mm of a 20 mm stack), 1-inch flat platen, 5 cycles.",
        [sample("Synthetic gasket foam", "", "", "", "", "", "", 6)], spec="ASTM D1056", due="2025-07-29",
        why=["Precise method: strain, speed, platen and cycles.", "Cites the material standard."],
        gaps=["Requested date is before the request date.", "No foam grade, lot or acceptance limit."], status="Prototype", project="Operational Support"),
    req(15, "2025-08-19", "FTIR on a melted area", "FTIR.", [sample("Synthetic high-speed connector", "SYN-41515 Rev A", "", "CuTi", AUNI, "None", "", 1)],
        spec="Need FTIR on the melted area to identify the polymer.", kind="contrast", due="2024-12-01", fmt="", dispo="",
        why=["Asks one question: identify the polymer."], gaps=["Requested date months before the request.", "No background on the melted area.", "Results format and disposition blank."],
        status="Prototype", project="Operational Support", legacy="Lab/Failure Analysis"),
    req(16, "2025-09-02", "Lab equipment check: current shunts", "Verify shunt resistance before use: source meter and nanovoltmeter, current reversal in differential mode, 100 mA, at most 20 mV across the shunt, at least 5 readings.",
        [sample("Current shunts", "Various", "Various", "Manganin", "N/A", "N/A", "N/A", "As needed")], spec="EIA-364-23",
        why=["Full measurement method.", "Cites the method standard."], gaps=["No tolerance per shunt; no list of shunt IDs.", "Standing request for the lab's own equipment."],
        dispo="Keep in the lab", conf="no", project="", legacy="Lab/Failure Analysis"),
    req(17, "2025-09-16", "Socket current rating in two phases", "Phase 1: LLCR, 6-hour current rating, LLCR, SEM/EDX. Phase 2: LLCR, 500-hour current rating, LLCR, SEM/EDX.",
        [sample("Synthetic CPU socket", "", "", CU, "", "", "", 15)], spec="EIA-364-23; EIA-364-70",
        info="Assembly includes backplate, host board, frame, package, film heater, heat sink and fan. Customer B test plan referenced. Power supplies and heater controllers must be bought first.",
        why=["Two phases with full sequences.", "A standard for each measurement.", "Lists the assembly and flags equipment to buy first."],
        gaps=["No part number or lot.", "Current target only in the customer plan."], status="Pre-Production", legacy="Product/Process Development"),
    req(18, "2025-09-30", "FIB plating analysis at marked spots", "FIB and SEM.",
        [sample("Synthetic receptacle", "SYN-41818 Rev A", "Supplier lot", "C17200", AUNI, "N/A", "N/A", 2), sample("Synthetic plug", "SYN-41819 Rev A", "Supplier lot", "C72500", AUNI, "N/A", "N/A", 2)],
        info="Report Au thickness or layering, Au porosity, Ni thickness, Ni porosity and grain structure. Two FIB cuts per contact, trench at least 20 µm wide. Photos circle the cut locations on the plug pin and the receptacle beam.",
        why=["Lists every result wanted.", "Says where and how much to cut, with photos."], gaps=["Test line says only 'FIB and SEM'.", "No plating specification to compare against."],
        project="Operational Support", legacy="Lab/Failure Analysis"),
    req(19, "2025-10-14", "CT wipe distance at three stack heights", "CT scan the connectors on their boards from the side; focus on the copper contacts. Measure wipe distance on each sample, from the centre of the receptacle contact to the edge of the plug contact.",
        [sample("Synthetic floating connector, 23 mm stack", "N/A", "N/A", CU, AUNI, "N/A", "LCP", 2), sample("Synthetic floating connector, 23.6 mm stack", "N/A", "N/A", CU, AUNI, "N/A", "LCP", 2),
         sample("Synthetic floating connector, 22.4 mm stack", "N/A", "N/A", CU, AUNI, "N/A", "LCP", 2)],
        info="A section drawing marks the distance to measure.", why=["Says what to focus on and what to ignore.", "One clear measurement per sample, three stack heights."],
        gaps=["No part numbers or lots.", "No expected wipe or limit."], status="Pre-Production", fmt="Formal Report (Internal)", legacy="Customer Specific Testing"),
    req(20, "2025-10-28", "Retention force with a minimum", "Contact retention: push 5 contacts per interposer (of 9 loaded), and push 5 inserts out of the housing; pick locations at random.",
        [sample("Synthetic interposer A", "SYN-42020 Rev A", "", "Copper alloy NK", AUNI, "", "LCP", 1), sample("Synthetic interposer B", "SYN-42021 Rev A", "", "Copper alloy NK", AUNI, "", "LCP", 1)],
        spec="Force 10 g minimum", info="A CAD view highlights the insert to push.",
        why=["States the pass limit.", "How many and how to pick them.", "Highlights the feature in a picture."], gaps=["No lots.", "Objective not stated."], status="Pre-Production"),
    req(21, "2025-11-11", "Conductor fracture: which failure mode?", "SEM of the broken conductor surfaces to identify the failure mode.",
        [sample("Synthetic cable assembly", "SYN-42121 Rev A", "Lot SYN-L2521", "CuTi", "Au", "", "", 1)],
        info="Broken conductors are in row 4 of the plug, on the side without the dust cap. Need to assess the break: tensile with necking, shear cut, or embrittlement from oxidation? Destructive testing is approved; the cables may need separating.",
        why=["Asks a specific question with candidate answers.", "Says where to look and approves destructive work."], gaps=["Two working days for a customer report.", "No usage history."],
        fmt="Formal Report (Customer)", project="Operational Support", legacy="Lab/Failure Analysis"),
    req(22, "2025-11-25", "Dye and pry with a pass rule", "Dye and pry.", [sample("Synthetic stacking connector, aged group C", "SYN-42222 Rev B", "From SYN-LR-PRIOR-22 group C", "C70250", "0.76 µm Au over Ni", "n/a", "LCP", 2),
                                                             sample("Synthetic stacking connector, new", "SYN-42222 Rev B", "TBD (new samples)", "C70250", "0.76 µm Au over Ni", "n/a", "LCP", 4)],
        spec="SYN-GS-2038", rev="SYN-GS-2038 Rev 6", info="Pass: no dye on the solder joint fracture surfaces.",
        why=["States the pass criterion.", "Traces samples to an earlier group and adds new samples as a baseline.", "Cites the procedure with revision."], gaps=["New-sample lot TBD.", "Test line is two words."], status="Pre-Production"),
    req(23, "2025-12-09", "Thermal cycling with humidity", "Thermal cycling: 25 °C to 65 °C with humidity, 10 cycles of 10 hours (100 hours), 2-hour ramps. 4 samples per design (C1-C4).",
        [sample("Shield attach, glue", "", "", "", "", "", "", 4), sample("Shield attach, solder paste", "", "", "", "", "", "", 4), sample("Shield attach, gasket", "", "", "", "", "", "", 4)],
        spec="EIA-364-31", rev="EIA-364-31 Rev F", why=["Full cycling profile.", "Cites the method.", "Same sample IDs for each design."],
        gaps=["No dwell or humidity level.", "Does not say what to measure before and after."], status="Prototype"),
    req(24, "2026-01-13", "DSC on a two-part epoxy", "DSC: two heating cycles for glass transition and residual exotherm; a 25-250 °C cure scan at 10 °C/min for onset, peak and total heat; post-cure Tg on the second heat.",
        [sample("Synthetic cured epoxy", "SYN-EPX-1", "", "", "", "", "", 1), sample("Field return fragments", "SYN-42424", "Lot SYN-L2601", "", "", "", "", 1), sample("Synthetic epoxy, liquid", "SYN-EPX-1", "", "", "", "", "", 1)],
        spec="ASTM E1356; ASTM E537", why=["Complete DSC method and outputs.", "Cites both methods.", "Compares cured, liquid and field-return samples."],
        gaps=["No quantities.", "No expected values."], status="Pre-Production"),
    req(25, "2026-01-27", "Contact force without cutting the housing", "Use an L-shaped probe on the front rows of both ports; mate to a board for the lowest beam. Test 1: 3 cycles to 0.40 mm, first and last maximum force. Test 2: full-travel curves per wafer type.",
        [sample("Synthetic stacked cage connector", "SYN-42525 Rev A", "Build 2026-01", "", "", "", "", 1)], spec="EIA-364-04",
        info="Wafer pattern 1-13: G-S-S-G-S-S-LS-S-S-G-S-S-G. Measure 2 ground, 2 signal and 1 low-speed wafer.",
        why=["Says how to test without destroying the part.", "Two tests with deflection and cycles.", "Gives the wafer pattern and counts."], gaps=["No normal-force minimum."]),
    req(26, "2026-02-10", "Validation with pass criteria", "Short temperature life: 72 h at 105 °C with CT, contact height and LLCR before and after (3 samples). Vibration and mechanical shock with LLCR before and after (3 samples).",
        [sample("Synthetic backstack connector", "", "", "", "", "", "", 6)], spec="EIA-364-28 condition Y; EIA-364-27 condition A",
        info="Pass: at most 10 mΩ change in LLCR, no visual damage, no discontinuity over 1 µs per EIA-364-46.",
        why=["States pass criteria.", "Cites each method and condition.", "Sample counts per group."], gaps=["No part numbers or lots.", "No requested date."], project="Operational Support", legacy="Product/Process Qualification"),
    req(27, "2026-02-24", "Coating DOE on LLCR", "Baseline LLCR on all mated pairs; unmate; cap one group; coating supplier coats and measures; remate; post-coating LLCR. Compare by board pair, side, thickness and cap condition.",
        [sample("Synthetic 100-position array", "", "", "", "", "", "", "18 pairs")],
        info="Purpose: does the coating process, its thickness or the cap change LLCR? Groups: 3 pairs light, 3 medium, 3 heavy, 5 heavy for Customer A's cleaning trial, 4 heavy with cap. Drawings circle the areas to mask.",
        why=["States the purpose in one line.", "Defines the DOE groups and counts.", "Step plan with hand-offs and how to report."],
        gaps=["No part numbers or lots.", "No LLCR shift limit or target thicknesses."], project="Operational Support", legacy="Customer Specific Testing"),
    req(28, "2026-03-10", "Gasket ageing: two suppliers by three conditions", "FTIR and TGA. Provide each spectrum and an overlay of baseline, thermal-aged and 85/85 samples, normalised to baseline. Report decomposition onset and filler content.",
        [sample("Supplier X gasket, baseline", "", "N/A", "", "", "", "", 1), sample("Supplier X gasket, 125 °C 72 days", "", "N/A", "", "", "", "", 1), sample("Supplier X gasket, 85 °C/85 %RH 72 days", "", "N/A", "", "", "", "", 1),
         sample("Supplier Y gasket, baseline", "", "N/A", "", "", "", "", 1), sample("Supplier Y gasket, 125 °C 72 days", "", "N/A", "", "", "", "", 1), sample("Supplier Y gasket, 85 °C/85 %RH 72 days", "", "N/A", "", "", "", "", 1)],
        info="The top surface discoloured; the glass-contact side less so. FTIR on both faces; the bottom face is marked red.",
        why=["Clean supplier-by-condition grid.", "Says how to present results.", "Explains an observation and asks for both faces."], gaps=["No lots.", "No requested date."], status="Pre-Production", legacy="Product/Process Qualification"),
    req(29, "2026-03-24", "Abrasion method on plated plastic", "Sliding abrasion at 20, 40 and 60 g with 320-grit paper over a 5 mm stroke. Top-view photo before and after each load. Plating thickness by section after each test.",
        [sample("Synthetic plated housing", "SYN-42929 Rev 2", "Date code 2026-03", "N/A", "Ni/Cu", "N/A", "LCP", 6)],
        why=["Full abrasion method.", "Photos and thickness after each load."], gaps=["Number of strokes not stated.", "No pass criterion."], fmt="Formal Report (Internal)", legacy="Product/Process Qualification"),
    req(30, "2026-04-07", "CT scan with no question", "CT scan of all submitted samples.",
        [sample("Design A", "", "", "", "", "", "", 5), sample("Design B", "", "", "", "", "", "", 5), sample("Design C", "", "", "", "", "", "", 4)], kind="contrast", due="2026-04-07",
        why=["Groups samples by design."], gaps=["Same-day request.", "No part numbers, lots or materials.", "Doesn't say what to look for."], status="Prototype"),
]


def build():
    from assistant import quality
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("SYN-LR-*.json"):
        old.unlink()
    index = {"_about": NOTICE + " Built by tools/make_synthetic_library.py.", "synthetic": True, "examples": []}
    contact = {"firstName", "lastName", "email", "phone", "bPCNumber", "sendCopiesTo"}
    for r in LIBRARY:
        rid = f"SYN-LR-{r['n']:03d}"
        title = f"[SYNTHETIC] {r['title']}"
        review = quality.review("lab_test_request", r["fields"], today=dt.date.fromisoformat(r["date"]))
        flags = [f for f in review["flags"] if f["field"] not in contact and not str(f.get("source") or "").startswith("SYN-TM")]
        rec = {"id": rid, "synthetic": True, "_notice": NOTICE, "form": "lab_test_request", "title": title,
               "kind": "good example" if r["kind"] == "good" else "contrast example (what to avoid)",
               "source": "synthetic, written to mirror patterns in a private library of real requests",
               "fields": r["fields"],
               "lab_section": {"request_date": r["date"], "reviewed_and_approved_by_lab": True, "legacy_test_type": r["legacy_test_type"]},
               "quality_at_request_date": {"must_fix": [f["message"] for f in flags if f["severity"] == "error"],
                                           "should_fix": [f["message"] for f in flags if f["severity"] == "warn"],
                                           "good_practice": [f["message"] for f in flags if f["severity"] == "info"]},
               "why_good": r["why_good"], "gaps": r["gaps"]}
        (OUT / f"{rid}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
        index["examples"].append({"id": rid, "form": "lab_test_request", "title": title, "kind": rec["kind"],
                                  "why_good": r["why_good"], "file": f"{rid}.json", "synthetic": True})
    (OUT / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8")
    (OUT / "README.md").write_text(f"""# SYNTHETIC past lab requests

**Everything in this folder is synthetic.** {NOTICE}

These {len(LIBRARY)} requests mirror the patterns of a private library of real past requests kept outside the repository
(`data/private/`, gitignored): the mix of test types, what good requests state (objective, method, pass criteria,
sample groups, traceability, pictures of the feature) and what they typically leave out (revisions, lots, limits,
plans in attachments, same-day dates). Use them to see what a good request looks like and what the quality check flags.

- `SYN-LR-NNN.json`: one request, in the form's own field names, with `why_good`, `gaps`, and the quality check's
  flags as of its request date (`quality_at_request_date`).
- `kind`: *good example*, or *contrast example (what to avoid)*.
- Part numbers are `SYN-`, internal specifications `SYN-GS-`, sites and units `SITE-A` / `BU-A`, customers
  "Customer A/B". Public standards (EIA-364, ASTM, IEC) are cited by number only.

Rebuild with `python tools/make_synthetic_library.py`.
""", encoding="utf-8")
    goods = sum(1 for r in LIBRARY if r["kind"] == "good")
    print(f"[synthetic] wrote {len(LIBRARY)} requests ({goods} good, {len(LIBRARY) - goods} contrast) to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    build()
