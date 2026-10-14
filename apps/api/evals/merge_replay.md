# In-batch merge replay (M9 part 2, R3)

Same-page pairs of production grown concepts with label cosine ≥ 0.85 (added_at ≤
2026-10-14 09:24:55 UTC). Verdicts were judged blind by the implementing agent and
committed (`merge_verdicts.json`, 9e4e138) before the model was asked. The model is asked
exactly as growth asks about two picks of one batch: `link_merge` on MODEL_FAST, two bare
labels. Cost $0.0032.

**61 pairs: false merges 0 (0 at cosine ≥ 0.899), missed duplicates 0.**

| cosine | a | b | verdict (blind) | model | |
|---|---|---|---|---|---|
| 0.971 | PFAS | PFOS | different | different |  |
| 0.960 | Phase 1 environmental site assessment | Phase 2 environmental site assessment | different | different |  |
| 0.958 | FORM GST REG-01 | FORM GST REG-14 | different | different |  |
| 0.940 | Edge (graph theory) | Node (graph theory) | different | different |  |
| 0.929 | Linear algebra | System of linear equations | different | different |  |
| 0.925 | Calendar phishing | Phishing | different | different |  |
| 0.925 | Tax-aware investing | Tax-loss harvesting | different | different |  |
| 0.914 | Tax liability | Tax loophole | different | different |  |
| 0.913 | Education Minister | Interior Minister | different | different |  |
| 0.908 | Flagship smartphone | Qualcomm Snapdragon 8 Elite | different | different |  |
| 0.899 | Contempt of court | Rule of law | different | different |  |
| 0.899 | Forever chemicals | PFAS | same | same |  |
| 0.899 | Tax loophole | Tax-loss harvesting | different | different |  |
| 0.899 | Knowledge graph | Node (graph theory) | different | different |  |
| 0.899 | Edge (graph theory) | Knowledge graph | different | different |  |
| 0.898 | Decompiler | Reverse engineering | different | different |  |
| 0.897 | Knowledge graph | Ontology (information science) | different | different |  |
| 0.897 | Automatic GST registration | FORM GST REG-01 | different | different |  |
| 0.895 | Antisemitism | Zionism | different | different |  |
| 0.895 | Anoxygenic photosynthesis | Bacteriorhodopsin | different | different |  |
| 0.892 | CPU architecture | Processor register | different | different |  |
| 0.891 | Forever chemicals | PFOS | different | different |  |
| 0.891 | Tax liability | Tax-loss harvesting | different | different |  |
| 0.889 | Executive Magistrate | Rule of law | different | different |  |
| 0.885 | Assembly language | Decompiler | different | different |  |
| 0.883 | Automatic GST registration | FORM GST REG-14 | different | different |  |
| 0.881 | Programmable Power Supply | USB Power Delivery | different | different |  |
| 0.881 | Contempt of court | Executive Magistrate | different | different |  |
| 0.879 | Tax-aware investing | Tax liability | different | different |  |
| 0.877 | Alarm photosynthesis | Anoxygenic photosynthesis | different | different |  |
| 0.877 | Franchise T20 leagues | Twenty20 centuries | different | different |  |
| 0.876 | Battery penetration test | Hot-box test | different | different |  |
| 0.875 | Assembler | Processor register | different | different |  |
| 0.875 | Tax-aware investing | Tax loophole | different | different |  |
| 0.873 | Twenty20 centuries | White-ball cricket | different | different |  |
| 0.871 | Preventive detention | Rule of law | different | different |  |
| 0.870 | Antisemitism | Apartheid | different | different |  |
| 0.869 | Assembler | CPU architecture | different | different |  |
| 0.868 | Humanoid robot | Wearable technology | different | different |  |
| 0.866 | PFAS | Phase 1 environmental site assessment | different | different |  |
| 0.866 | First Information Report | Seizure memo | different | different |  |
| 0.865 | eSIM | Wearable technology | different | different |  |
| 0.865 | Circle Inspector and Sub-Inspector | Watch and Ward | different | different |  |
| 0.865 | Knowledge graph | Natural language processing | different | different |  |
| 0.865 | Battery penetration test | Silicon-carbon battery | different | different |  |
| 0.864 | Apple A18 | Flagship smartphone | different | different |  |
| 0.863 | Blasphemy | Capital punishment | different | different |  |
| 0.863 | Node (graph theory) | Ontology (information science) | different | different |  |
| 0.859 | Alarm photosynthesis | C2 photorespiratory carbon pump | different | different |  |
| 0.859 | PFAS | Phase 2 environmental site assessment | different | different |  |
| 0.858 | Payment service provider | Peer-to-peer transaction | different | different |  |
| 0.858 | Apple A18 | Qualcomm Snapdragon 8 Elite | different | different |  |
| 0.857 | Chief Election Commissioner | Executive Magistrate | different | different |  |
| 0.857 | FORM GST REG-01 | Permanent Account Number | different | different |  |
| 0.855 | Edge (graph theory) | Ontology (information science) | different | different |  |
| 0.854 | Assembly language | Reverse engineering | different | different |  |
| 0.854 | Strike rate | White-ball cricket | different | different |  |
| 0.853 | Action spectrum | Bacteriorhodopsin | different | different |  |
| 0.852 | Executive Magistrate | Preventive detention | different | different |  |
| 0.851 | Natural language processing | Ontology (information science) | different | different |  |
| 0.850 | BSS section | Segmentation fault | different | different |  |
