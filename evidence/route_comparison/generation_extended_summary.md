# Generation comparison (extended library)

Chat model Qwen/Qwen3.5-9B (NVIDIA RTX 5000 Ada Generation Laptop GPU, quantization 4bit); retrieval bge-base, section chunks. Coverage = share of a scenario's output checks found in the draft (regex, approximate). Forbidden = obsolete or inapplicable rules repeated in the draft.

| Route | Coverage (mean) | Coverage (worst) | Forbidden (total) | Retrieval recall | Context words | s / draft |
|---|---|---|---|---|---|---|
| everything in scope (no ranking) | 0.94 | 0.83 | 0 | 1.00 | 993 | 43 |
| form sections, filtered, 1/section | 0.78 | 0.56 | 0 | 0.77 | 259 | 33 |
| request, filtered, k=5 | 0.66 | 0.33 | 0 | 0.48 | 200 | 31 |
| request, filtered, MMR 0.7, k=5 | 0.62 | 0.33 | 0 | 0.39 | 186 | 27 |
| request, unfiltered, k=5 | 0.58 | 0.22 | 0 | 0.21 | 199 | 30 |
| no retrieval | 0.27 | 0.00 | 0 | 0.00 | 0 | 22 |

## Per scenario

| Scenario | Route | Coverage | Forbidden found | Missed checks |
|---|---|---|---|---|
| S1_warpage_reflow | no retrieval | 0.00 | — | asks for thermal profile; measurement area / datum; preconditioning; bake 125 C / 24 h; 25 C baseline; no second profile; minimum 5 samples; contour maps choice; storage history |
| S1_warpage_reflow | request, unfiltered, k=5 | 0.22 | — | preconditioning; bake 125 C / 24 h; 25 C baseline; no second profile; minimum 5 samples; contour maps choice; storage history |
| S1_warpage_reflow | request, filtered, k=5 | 0.56 | — | bake 125 C / 24 h; minimum 5 samples; contour maps choice; storage history |
| S1_warpage_reflow | request, filtered, MMR 0.7, k=5 | 0.67 | — | bake 125 C / 24 h; minimum 5 samples; storage history |
| S1_warpage_reflow | form sections, filtered, 1/section | 0.56 | — | bake 125 C / 24 h; minimum 5 samples; contour maps choice; storage history |
| S1_warpage_reflow | everything in scope (no ranking) | 0.89 | — | no second profile |
| S2_warpage_paraphrased | no retrieval | 0.17 | — | asks for thermal profile; preconditioning; bake 125 C / 24 h; 25 C baseline; minimum 5 samples |
| S2_warpage_paraphrased | request, unfiltered, k=5 | 0.33 | — | preconditioning; bake 125 C / 24 h; 25 C baseline; minimum 5 samples |
| S2_warpage_paraphrased | request, filtered, k=5 | 0.33 | — | preconditioning; bake 125 C / 24 h; 25 C baseline; minimum 5 samples |
| S2_warpage_paraphrased | request, filtered, MMR 0.7, k=5 | 0.33 | — | preconditioning; bake 125 C / 24 h; 25 C baseline; minimum 5 samples |
| S2_warpage_paraphrased | form sections, filtered, 1/section | 0.83 | — | bake 125 C / 24 h |
| S2_warpage_paraphrased | everything in scope (no ranking) | 1.00 | — | — |
| S3_flatness_room_temp | no retrieval | 0.50 | — | 2 h stabilization; minimum 10 samples per lot |
| S3_flatness_room_temp | request, unfiltered, k=5 | 1.00 | — | — |
| S3_flatness_room_temp | request, filtered, k=5 | 0.75 | — | minimum 10 samples per lot |
| S3_flatness_room_temp | request, filtered, MMR 0.7, k=5 | 0.75 | — | minimum 10 samples per lot |
| S3_flatness_room_temp | form sections, filtered, 1/section | 1.00 | — | — |
| S3_flatness_room_temp | everything in scope (no ranking) | 1.00 | — | — |
| S4_thermal_cycling | no retrieval | 0.50 | — | preconditioning; bake; what is measured at readouts |
| S4_thermal_cycling | request, unfiltered, k=5 | 0.83 | — | bake |
| S4_thermal_cycling | request, filtered, k=5 | 0.83 | — | bake |
| S4_thermal_cycling | request, filtered, MMR 0.7, k=5 | 0.83 | — | bake |
| S4_thermal_cycling | form sections, filtered, 1/section | 0.83 | — | bake |
| S4_thermal_cycling | everything in scope (no ranking) | 1.00 | — | — |
| S5_combined_reflow_cycling | no retrieval | 0.17 | — | flags second-profile rule; preconditioning; minimum 5 samples; asks reflow profile; storage window |
| S5_combined_reflow_cycling | request, unfiltered, k=5 | 0.50 | — | flags second-profile rule; minimum 5 samples; storage window |
| S5_combined_reflow_cycling | request, filtered, k=5 | 0.83 | — | storage window |
| S5_combined_reflow_cycling | request, filtered, MMR 0.7, k=5 | 0.50 | — | flags second-profile rule; minimum 5 samples; storage window |
| S5_combined_reflow_cycling | form sections, filtered, 1/section | 0.67 | — | flags second-profile rule; storage window |
| S5_combined_reflow_cycling | everything in scope (no ranking) | 0.83 | — | flags second-profile rule |
