"""
Mission registry for SPICE operations.

Maps mission IDs to NAIF integer IDs, kernel source URLs,
and provides fuzzy mission name resolution.
"""

# ---------------------------------------------------------------------------
# NAIF ID mapping
# ---------------------------------------------------------------------------

# Maps mission keys (uppercase) to NAIF body/spacecraft IDs.
# Negative IDs are spacecraft; positive are natural bodies.
MISSION_NAIF_IDS: dict[str, int] = {
    # Heliophysics missions
    "PSP": -96,
    "SOLO": -144,
    "IBEX": -163,
    "SOHO": -21,
    "RBSP_A": -362,
    "RBSP_B": -363,
    "STEREO_A": -234,
    "STEREO_B": -235,
    "HELIOS_1": -301,
    "HELIOS_2": -302,
    "ULYSSES": -55,
    "THEMIS_A": -650,
    "THEMIS_B": -651,  # aka ARTEMIS P1
    "THEMIS_C": -652,  # aka ARTEMIS P2
    "THEMIS_D": -653,
    "THEMIS_E": -654,
    "PIONEER_6": -6,
    "PIONEER_8": -8,
    # Planetary / deep-space missions
    "VEX": -248,
    "PIONEER_VENUS": -12,
    "INSIGHT": -189,
    "LRO": -85,
    "LUNAR_PROSPECTOR": -25,
    "MGS": -94,
    "CASSINI": -82,
    "JUNO": -61,
    "VOYAGER_1": -31,
    "VOYAGER_2": -32,
    "MAVEN": -202,
    "GALILEO": -77,
    "PIONEER_10": -23,
    "PIONEER_11": -24,
    "MESSENGER": -236,
    "NEW_HORIZONS": -98,
    "DAWN": -203,
    "LUCY": -49,
    "EUROPA_CLIPPER": -159,
    "PSYCHE": -255,
    "JUICE": -28,
    "BEPICOLOMBO": -121,
    "MARS_2020": -168,
    "MRO": -74,
    "MEX": -41,
    "MARS_ODYSSEY": -53,
    "MSL": -76,
    "PHOENIX": -84,
    "NEAR": -93,
    "DEEP_IMPACT": -140,
    "EPOXI": -140,
    "HAYABUSA": -130,
    "VIKING_1": -27,
    "VIKING_2": -30,
    "MER_SPIRIT": -253,
    "MER_OPPORTUNITY": -254,
    "ROSETTA": -226,
    "CLEMENTINE": -40,
    "DEEP_SPACE_1": -30,
    "OSIRIS_REX": -64,
    "MAGELLAN": -18,
    "EXOMARS_TGO": -143,
    "SMART_1": -238,
    "GENESIS": -47,
    "GIOTTO": -78,  # NAIF uses -78 in SPK files (not -20 from older references)
    "MARINER_9": -9,
    "MARINER_10": -10,
    "VEGA_1": -11,
    "STARDUST": -29,
    "CONTOUR": -36,
    "IUE": -43,
    "LADEE": -397,
    "AKATSUKI": -5,
    "GRAIL_A": -177,
    "GRAIL_B": -178,
    "CHANDRAYAAN_1": -86,
    "LUNAR_ORBITER_1": -1,
    "LUNAR_ORBITER_2": -2,
    "LUNAR_ORBITER_3": -3,
    "LUNAR_ORBITER_4": -4,
    "LUNAR_ORBITER_5": -5,
    "HERA": -658,
    # Observatories
    "JWST": -170,
    "HST": -48,
    "CHANDRA": -151,
    "SPITZER": -79,
    "GAIA": -123,
    "EUCLID": -171,
    "INTEGRAL": -198,
    # Natural bodies (for observer/target)
    "SUN": 10,
    "EARTH": 399,
    "MOON": 301,
    "MERCURY": 199,
    "VENUS": 299,
    "MARS": 4,        # Barycenter — body center (499) not in de440s.bsp
    "JUPITER": 5,     # Barycenter — body center (599) not in de440s.bsp
    "SATURN": 6,      # Barycenter — body center (699) not in de440s.bsp
    "URANUS": 7,      # Barycenter — body center (799) not in de440s.bsp
    "NEPTUNE": 8,     # Barycenter — body center (899) not in de440s.bsp
    "PLUTO": 9,       # Barycenter — body center (999) not in de440s.bsp
    # Barycenters
    "SSB": 0,  # Solar System Barycenter
    "EARTH_BARYCENTER": 3,
    "MARS_BARYCENTER": 4,
    "JUPITER_BARYCENTER": 5,
    "SATURN_BARYCENTER": 6,
}

# Aliases: common names -> canonical mission key
_ALIASES: dict[str, str] = {
    "PARKER": "PSP",
    "PARKER SOLAR PROBE": "PSP",
    "SOLAR ORBITER": "SOLO",
    "SOLAR_ORBITER": "SOLO",
    "SOLORB": "SOLO",
    "STEREOA": "STEREO_A",
    "STEREO-A": "STEREO_A",
    "STEREOB": "STEREO_B",
    "STEREO-B": "STEREO_B",
    "VOYAGER1": "VOYAGER_1",
    "VOYAGER 1": "VOYAGER_1",
    "VGR1": "VOYAGER_1",
    "VOYAGER2": "VOYAGER_2",
    "VOYAGER 2": "VOYAGER_2",
    "VGR2": "VOYAGER_2",
    "PIONEER10": "PIONEER_10",
    "PIONEER 10": "PIONEER_10",
    "PIONEER11": "PIONEER_11",
    "PIONEER 11": "PIONEER_11",
    "NEWHORIZONS": "NEW_HORIZONS",
    "NEW HORIZONS": "NEW_HORIZONS",
    "NH": "NEW_HORIZONS",
    "HELIOS1": "HELIOS_1",
    "HELIOS 1": "HELIOS_1",
    "HELIOS2": "HELIOS_2",
    "HELIOS 2": "HELIOS_2",
    "THEMIS": "THEMIS_A",
    "ARTEMIS_P1": "THEMIS_B",
    "ARTEMIS P1": "THEMIS_B",
    "ARTEMIS_P2": "THEMIS_C",
    "ARTEMIS P2": "THEMIS_C",
    "EUROPA CLIPPER": "EUROPA_CLIPPER",
    "EUROPACLIPPER": "EUROPA_CLIPPER",
    "CLIPPER": "EUROPA_CLIPPER",
    "PERSEVERANCE": "MARS_2020",
    "MARS2020": "MARS_2020",
    "MARS 2020": "MARS_2020",
    "BEPI": "BEPICOLOMBO",
    "BEPI COLOMBO": "BEPICOLOMBO",
    "BEPI_COLOMBO": "BEPICOLOMBO",
    "MPO": "BEPICOLOMBO",
    "VAN ALLEN PROBE A": "RBSP_A",
    "VAN_ALLEN_PROBE_A": "RBSP_A",
    "RBSPA": "RBSP_A",
    "VAN ALLEN PROBE B": "RBSP_B",
    "VAN_ALLEN_PROBE_B": "RBSP_B",
    "RBSPB": "RBSP_B",
    "VENUS EXPRESS": "VEX",
    "VENUS_EXPRESS": "VEX",
    "PVO": "PIONEER_VENUS",
    "PIONEER 12": "PIONEER_VENUS",
    "PIONEER_12": "PIONEER_VENUS",
    "PIONEER VENUS ORBITER": "PIONEER_VENUS",
    "NSYT": "INSIGHT",
    "LUNAR PROSPECTOR": "LUNAR_PROSPECTOR",
    "LP": "LUNAR_PROSPECTOR",
    "MARS GLOBAL SURVEYOR": "MGS",
    "MARS_GLOBAL_SURVEYOR": "MGS",
    # New missions — planetary flagships
    "CURIOSITY": "MSL",
    "MARS SCIENCE LABORATORY": "MSL",
    "MARS_SCIENCE_LABORATORY": "MSL",
    "NEAR SHOEMAKER": "NEAR",
    "NEAR_SHOEMAKER": "NEAR",
    "JAMES WEBB": "JWST",
    "JAMES WEBB SPACE TELESCOPE": "JWST",
    "JAMES_WEBB_SPACE_TELESCOPE": "JWST",
    "WEBB": "JWST",
    "HUBBLE": "HST",
    "HUBBLE SPACE TELESCOPE": "HST",
    "HUBBLE_SPACE_TELESCOPE": "HST",
    "MARS EXPRESS": "MEX",
    "MARS_EXPRESS": "MEX",
    "SPIRIT": "MER_SPIRIT",
    "MER1": "MER_SPIRIT",
    "MER 1": "MER_SPIRIT",
    "MER-1": "MER_SPIRIT",
    "MER A": "MER_SPIRIT",
    "MER_A": "MER_SPIRIT",
    "OPPORTUNITY": "MER_OPPORTUNITY",
    "OPPY": "MER_OPPORTUNITY",
    "MER2": "MER_OPPORTUNITY",
    "MER 2": "MER_OPPORTUNITY",
    "MER-2": "MER_OPPORTUNITY",
    "MER B": "MER_OPPORTUNITY",
    "MER_B": "MER_OPPORTUNITY",
    "VIKING 1": "VIKING_1",
    "VIKING 2": "VIKING_2",
    "VIKING ORBITER 1": "VIKING_1",
    "VIKING_ORBITER_1": "VIKING_1",
    "VIKING ORBITER 2": "VIKING_2",
    "VIKING_ORBITER_2": "VIKING_2",
    "VO1": "VIKING_1",
    "VO2": "VIKING_2",
    "DS1": "DEEP_SPACE_1",
    "DS-1": "DEEP_SPACE_1",
    "DEEP SPACE 1": "DEEP_SPACE_1",
    "DEEP SPACE ONE": "DEEP_SPACE_1",
    "DI": "DEEP_IMPACT",
    "DEEP IMPACT": "DEEP_IMPACT",
    "DEEP IMPACT FLYBY": "DEEP_IMPACT",
    "OSIRIS-REX": "OSIRIS_REX",
    "OSIRIS REX": "OSIRIS_REX",
    "OSIRISREX": "OSIRIS_REX",
    "ORX": "OSIRIS_REX",
    "OSIRIS-APEX": "OSIRIS_REX",
    "OSIRIS APEX": "OSIRIS_REX",
    "HAYABUSA 1": "HAYABUSA",
    "HAYABUSA1": "HAYABUSA",
    "MUSES-C": "HAYABUSA",
    "MUSES C": "HAYABUSA",
    "MARINER 9": "MARINER_9",
    "MARINER9": "MARINER_9",
    "MARINER 10": "MARINER_10",
    "MARINER10": "MARINER_10",
    "VEGA 1": "VEGA_1",
    "VEGA1": "VEGA_1",
    "LO1": "LUNAR_ORBITER_1",
    "LO2": "LUNAR_ORBITER_2",
    "LO3": "LUNAR_ORBITER_3",
    "LO4": "LUNAR_ORBITER_4",
    "LO5": "LUNAR_ORBITER_5",
    "LUNAR ORBITER 1": "LUNAR_ORBITER_1",
    "LUNAR ORBITER 2": "LUNAR_ORBITER_2",
    "LUNAR ORBITER 3": "LUNAR_ORBITER_3",
    "LUNAR ORBITER 4": "LUNAR_ORBITER_4",
    "LUNAR ORBITER 5": "LUNAR_ORBITER_5",
    "SMART1": "SMART_1",
    "SMART-1": "SMART_1",
    "SMART 1": "SMART_1",
    # New missions — segmented
    "MARS ODYSSEY": "MARS_ODYSSEY",
    "ODYSSEY": "MARS_ODYSSEY",
    "M01": "MARS_ODYSSEY",
    "VCO": "AKATSUKI",
    "VENUS CLIMATE ORBITER": "AKATSUKI",
    "VENUS_CLIMATE_ORBITER": "AKATSUKI",
    "GRAIL": "GRAIL_A",
    "GRAIL A": "GRAIL_A",
    "GRAIL EBB": "GRAIL_A",
    "GRAIL B": "GRAIL_B",
    "GRAIL FLOW": "GRAIL_B",
    "TGO": "EXOMARS_TGO",
    "EXOMARS": "EXOMARS_TGO",
    "EXOMARS TGO": "EXOMARS_TGO",
    "TRACE GAS ORBITER": "EXOMARS_TGO",
    "TRACE_GAS_ORBITER": "EXOMARS_TGO",
    "CHANDRAYAAN": "CHANDRAYAAN_1",
    "CHANDRAYAAN 1": "CHANDRAYAAN_1",
    "CHANDRAYAAN-1": "CHANDRAYAAN_1",
    "CH1": "CHANDRAYAAN_1",
    "MGN": "MAGELLAN",
    "SDU": "STARDUST",
    "DIF": "EPOXI",
    "SIRTF": "SPITZER",
    "SPITZER SPACE TELESCOPE": "SPITZER",
    "SPITZER_SPACE_TELESCOPE": "SPITZER",
    "CHANDRA X-RAY": "CHANDRA",
    "CXO": "CHANDRA",
}

# ---------------------------------------------------------------------------
# Kernel sources — URLs to NAIF/ESA kernel repositories
# ---------------------------------------------------------------------------

_NAIF_BASE = "https://naif.jpl.nasa.gov/pub/naif"

# Generic kernels needed by all missions
GENERIC_KERNELS: dict[str, str] = {
    "naif0012.tls": f"{_NAIF_BASE}/generic_kernels/lsk/naif0012.tls",
    "pck00011.tpc": f"{_NAIF_BASE}/generic_kernels/pck/pck00011.tpc",
    "de440s.bsp": f"{_NAIF_BASE}/generic_kernels/spk/planets/de440s.bsp",
    "gm_de440.tpc": f"{_NAIF_BASE}/generic_kernels/pck/gm_de440.tpc",
}

# Mission-specific kernel sets: {filename: url}
# Each mission needs at minimum an SPK (trajectory) file.
# Some also need FK (frame kernel), SCLK (clock kernel), etc.
MISSION_KERNELS: dict[str, dict[str, str]] = {
    "PSP": {
        "spp_nom_20180812_20300101_v043_PostV7.bsp": (
            "https://cdaweb.gsfc.nasa.gov/pub/data/psp/ephemeris/spice/ephemerides/"
            "spp_nom_20180812_20300101_v043_PostV7.bsp"
        ),
    },
    "SOLO": {
        "solo_ANC_soc-orbit-stp_20200210-20301120_399_V1_00513_V01.bsp": (
            "https://spiftp.esac.esa.int/data/SPICE/SOLAR-ORBITER/kernels/spk/"
            "solo_ANC_soc-orbit-stp_20200210-20301120_399_V1_00513_V01.bsp"
        ),
    },
    "STEREO_A": {
        "STEREO-A_merged.bsp": (
            f"{_NAIF_BASE}/STEREO/kernels/spk/"
            "STEREO-A_merged.bsp"
        ),
    },
    "STEREO_B": {
        "behind_2026_029_01.epm.bsp": (
            "https://sohoftp.nascom.nasa.gov/solarsoft/stereo/gen/data/spice/epm/behind/"
            "behind_2026_029_01.epm.bsp"
        ),
    },
    "JUNO": {
        "juno_rec_orbit.bsp": (
            f"{_NAIF_BASE}/JUNO/kernels/spk/"
            "juno_rec_orbit.bsp"
        ),
    },
    "VOYAGER_1": {
        "vgr1.x2100.bsp": (
            f"{_NAIF_BASE}/VOYAGER/kernels/spk/"
            "vgr1.x2100.bsp"
        ),
    },
    "VOYAGER_2": {
        "vgr2.x2100.bsp": (
            f"{_NAIF_BASE}/VOYAGER/kernels/spk/"
            "vgr2.x2100.bsp"
        ),
    },
    "MAVEN": {
        "maven_orb_rec.bsp": (
            f"{_NAIF_BASE}/MAVEN/kernels/spk/"
            "maven_orb_rec.bsp"
        ),
    },
    "NEW_HORIZONS": {
        "nh_pred_alleph_od161.bsp": (
            f"{_NAIF_BASE}/pds/data/nh-j_p_ss-spice-6-v1.0/nhsp_1000/data/spk/"
            "nh_pred_alleph_od161.bsp"
        ),
    },
    "ULYSSES": {
        "ulysses_1990_2009_2050.bsp": (
            f"{_NAIF_BASE}/ULYSSES/kernels/spk/"
            "ulysses_1990_2009_2050.bsp"
        ),
    },
    "PIONEER_10": {
        "p10-a.bsp": (
            f"{_NAIF_BASE}/PIONEER10/kernels/spk/"
            "p10-a.bsp"
        ),
    },
    "PIONEER_11": {
        "p11-a.bsp": (
            f"{_NAIF_BASE}/PIONEER11/kernels/spk/"
            "p11-a.bsp"
        ),
    },
    "GALILEO": {
        "gll_951120_021126_raj2021.bsp": (
            f"{_NAIF_BASE}/GLL/kernels/spk/"
            "gll_951120_021126_raj2021.bsp"
        ),
    },
    "HELIOS_1": {
        "100528R_helios1_74345_81272.bsp": (
            f"{_NAIF_BASE}/HELIOS/kernels/spk/"
            "100528R_helios1_74345_81272.bsp"
        ),
        "160707AP_helios1_81272_86074.bsp": (
            f"{_NAIF_BASE}/HELIOS/kernels/spk/"
            "160707AP_helios1_81272_86074.bsp"
        ),
    },
    "HELIOS_2": {
        "100607R_helios2_76016_80068.bsp": (
            f"{_NAIF_BASE}/HELIOS/kernels/spk/"
            "100607R_helios2_76016_80068.bsp"
        ),
    },
    "MESSENGER": {
        "msgr_040803_150430_150430_od431sc_2.bsp": (
            f"{_NAIF_BASE}/pds/data/mess-e_v_h-spice-6-v1.0/"
            "messsp_1000/data/spk/msgr_040803_150430_150430_od431sc_2.bsp"
        ),
    },
    "THEMIS_A": {
        "THEMIS_A_definitive_trajectory.bsp": (
            f"{_NAIF_BASE}/THEMIS/kernels/spk/"
            "THEMIS_A_definitive_trajectory.bsp"
        ),
    },
    "THEMIS_B": {
        "THEMIS_B_definitive_trajectory.bsp": (
            f"{_NAIF_BASE}/THEMIS/kernels/spk/"
            "THEMIS_B_definitive_trajectory.bsp"
        ),
    },
    "THEMIS_C": {
        "THEMIS_C_definitive_trajectory.bsp": (
            f"{_NAIF_BASE}/THEMIS/kernels/spk/"
            "THEMIS_C_definitive_trajectory.bsp"
        ),
    },
    "THEMIS_D": {
        "THEMIS_D_definitive_trajectory.bsp": (
            f"{_NAIF_BASE}/THEMIS/kernels/spk/"
            "THEMIS_D_definitive_trajectory.bsp"
        ),
    },
    "THEMIS_E": {
        "THEMIS_E_definitive_trajectory.bsp": (
            f"{_NAIF_BASE}/THEMIS/kernels/spk/"
            "THEMIS_E_definitive_trajectory.bsp"
        ),
    },
    "DAWN": {
        "dawn_p_181030-431030_181211_v1.bsp": (
            f"{_NAIF_BASE}/DAWN/kernels/spk/"
            "dawn_p_181030-431030_181211_v1.bsp"
        ),
    },
    "LUCY": {
        "lcy_250917_330402_250730_OD093-R-MEF2-P-TCM37a-P_v1.bsp": (
            f"{_NAIF_BASE}/LUCY/kernels/spk/"
            "lcy_250917_330402_250730_OD093-R-MEF2-P-TCM37a-P_v1.bsp"
        ),
    },
    "EUROPA_CLIPPER": {
        "trj_251001-260516-dco2601141914-cruise013-predict-OD078-v1.bsp": (
            f"{_NAIF_BASE}/EUROPACLIPPER/kernels/spk/"
            "trj_251001-260516-dco2601141914-cruise013-predict-OD078-v1.bsp"
        ),
    },
    "PSYCHE": {
        "psyche_sc-eph_250912-260601_260114_v1.bsp": (
            f"{_NAIF_BASE}/PSYCHE/kernels/spk/"
            "psyche_sc-eph_250912-260601_260114_v1.bsp"
        ),
    },
    "JUICE": {
        "juice_crema_5_1_150lb_23_1_v01.bsp": (
            f"{_NAIF_BASE}/JUICE/kernels/spk/"
            "juice_crema_5_1_150lb_23_1_v01.bsp"
        ),
    },
    "BEPICOLOMBO": {
        "bc_mtm_scp_cruise_20181016_20251205_v01.bsp": (
            f"{_NAIF_BASE}/BEPICOLOMBO/kernels/spk/"
            "bc_mtm_scp_cruise_20181016_20251205_v01.bsp"
        ),
    },
    "SOHO": {
        "soho_orbit.bsp": (
            "https://soho.nascom.nasa.gov/data/ancillary/orbit/spice/soho_orbit.bsp"
        ),
    },
    "IBEX": {
        "ibex_orbits_isoc_ephem_v2251.bsp": (
            "https://cdaweb.gsfc.nasa.gov/pub/data/ibex/orbits/"
            "ibex_orbits_isoc_ephem_v2251.bsp"
        ),
    },
    "RBSP_A": {
        "rbspa_2018_182_2019_291_01.deph.bsp": (
            "https://cdaweb.gsfc.nasa.gov/pub/data/rbsp/rbspa/ephemeris/ephemerides/"
            "rbspa_2018_182_2019_291_01.deph.bsp"
        ),
    },
    "RBSP_B": {
        "rbspb_2018_182_2019_200_01.deph.bsp": (
            "https://cdaweb.gsfc.nasa.gov/pub/data/rbsp/rbspb/ephemeris/ephemerides/"
            "rbspb_2018_182_2019_200_01.deph.bsp"
        ),
    },
    "VEX": {
        "ORVM_______________00001.BSP": (
            f"{_NAIF_BASE}/VEX/kernels/spk/"
            "ORVM_______________00001.BSP"
        ),
    },
    "PIONEER_VENUS": {
        "pvo_781209_820908_ssd1999.bsp": (
            f"{_NAIF_BASE}/PIONEER12/kernels/spk/"
            "pvo_781209_820908_ssd1999.bsp"
        ),
        "pvo_871229_880601_ssd1999.bsp": (
            f"{_NAIF_BASE}/PIONEER12/kernels/spk/"
            "pvo_871229_880601_ssd1999.bsp"
        ),
    },
    "INSIGHT": {
        "insight_cru_ops_v1.bsp": (
            f"{_NAIF_BASE}/INSIGHT/kernels/spk/"
            "insight_cru_ops_v1.bsp"
        ),
        "insight_ls_ops181206_iau2000_v1.bsp": (
            f"{_NAIF_BASE}/INSIGHT/kernels/spk/"
            "insight_ls_ops181206_iau2000_v1.bsp"
        ),
    },
    "ROSETTA": {
        "RORB_DV_257_03___T19_00345.BSP": (
            f"{_NAIF_BASE}/ROSETTA/kernels/spk/"
            "RORB_DV_257_03___T19_00345.BSP"
        ),
    },
    "NEAR": {
        "near_cruise_nav_v1.bsp": (
            f"{_NAIF_BASE}/pds/data/near-a-spice-6-v1.0/nearsp_1000/data/spk/"
            "near_cruise_nav_v1.bsp"
        ),
        "near_erosorbit_nav_v1.bsp": (
            f"{_NAIF_BASE}/pds/data/near-a-spice-6-v1.0/nearsp_1000/data/spk/"
            "near_erosorbit_nav_v1.bsp"
        ),
    },
    "DEEP_IMPACT": {
        "dif_preenc174_nav_v1.bsp": (
            f"{_NAIF_BASE}/pds/data/di-c-spice-6-v1.0/disp_1000/data/spk/"
            "dif_preenc174_nav_v1.bsp"
        ),
        "di_finalenc_nav_v3.bsp": (
            f"{_NAIF_BASE}/pds/data/di-c-spice-6-v1.0/disp_1000/data/spk/"
            "di_finalenc_nav_v3.bsp"
        ),
    },
    "EPOXI": {
        "dif_epoch_nav_v1.bsp": (
            f"{_NAIF_BASE}/pds/data/dif-c_e_x-spice-6-v1.0/epxsp_1000/data/spk/"
            "dif_epoch_nav_v1.bsp"
        ),
        "dif_dixi_nav_v1.bsp": (
            f"{_NAIF_BASE}/pds/data/dif-c_e_x-spice-6-v1.0/epxsp_1000/data/spk/"
            "dif_dixi_nav_v1.bsp"
        ),
    },
    "CLEMENTINE": {
        "clem_jpl.bsp": (
            f"{_NAIF_BASE}/pds/data/clem1-l-spice-6-v1.0/clsp_1000/data/spk/"
            "clem_jpl.bsp"
        ),
    },
    "DEEP_SPACE_1": {
        "ds1_radionav.bsp": (
            f"{_NAIF_BASE}/pds/data/ds1-a_c-spice-6-v1.0/ds1sp_1000/data/spk/"
            "ds1_radionav.bsp"
        ),
    },
    "MSL": {
        "msl_cruise_v1.bsp": (
            f"{_NAIF_BASE}/MSL/kernels/spk/"
            "msl_cruise_v1.bsp"
        ),
        "msl_surf_rover_loc.bsp": (
            f"{_NAIF_BASE}/MSL/kernels/spk/"
            "msl_surf_rover_loc.bsp"
        ),
    },
    "HAYABUSA": {
        "hayabusa_itokawarendezvous_v01.bsp": (
            f"{_NAIF_BASE}/pds/data/hay-a-spice-6-v1.0/haysp_1000/data/spk/"
            "hayabusa_itokawarendezvous_v01.bsp"
        ),
    },
    "OSIRIS_REX": {
        "orx_160909_231024_refod009_v2.bsp": (
            f"{_NAIF_BASE}/pds/pds4/orex/orex_spice/spice_kernels/spk/"
            "orx_160909_231024_refod009_v2.bsp"
        ),
    },
    "MEX": {
        "ORMF_240614_320101_01863.BSP": (
            f"{_NAIF_BASE}/MEX/kernels/spk/"
            "ORMF_240614_320101_01863.BSP"
        ),
    },
    "PHOENIX": {
        "phx_cruise.bsp": (
            f"{_NAIF_BASE}/PHOENIX/kernels/spk/"
            "phx_cruise.bsp"
        ),
        "phx_edl_rec_traj.bsp": (
            f"{_NAIF_BASE}/PHOENIX/kernels/spk/"
            "phx_edl_rec_traj.bsp"
        ),
    },
    "VIKING_1": {
        "vo1_rcon.bsp": (
            f"{_NAIF_BASE}/VIKING/kernels/spk/"
            "vo1_rcon.bsp"
        ),
    },
    "VIKING_2": {
        "vo2_rcon.bsp": (
            f"{_NAIF_BASE}/VIKING/kernels/spk/"
            "vo2_rcon.bsp"
        ),
    },
    "MER_SPIRIT": {
        "mer1_cruise.bsp": (
            f"{_NAIF_BASE}/MER/kernels/spk/"
            "mer1_cruise.bsp"
        ),
        "mer1_surf_rover.bsp": (
            f"{_NAIF_BASE}/MER/kernels/spk/"
            "mer1_surf_rover.bsp"
        ),
    },
    "MER_OPPORTUNITY": {
        "mer2_cruise.bsp": (
            f"{_NAIF_BASE}/MER/kernels/spk/"
            "mer2_cruise.bsp"
        ),
        "mer2_surf_rover_all_v01.bsp": (
            f"{_NAIF_BASE}/pds/data/mer2-m-spice-6-v1.0/mer2sp_1000/data/spk/"
            "mer2_surf_rover_all_v01.bsp"
        ),
    },
    "SMART_1": {
        "ORMS_______________00233.BSP": (
            f"{_NAIF_BASE}/SMART1/kernels/spk/"
            "ORMS_______________00233.BSP"
        ),
    },
    "JWST": {
        "jwst_rec.bsp": (
            f"{_NAIF_BASE}/JWST/kernels/spk/"
            "jwst_rec.bsp"
        ),
        "jwst_pred.bsp": (
            f"{_NAIF_BASE}/JWST/kernels/spk/"
            "jwst_pred.bsp"
        ),
    },
    "HST": {
        "hst.bsp": (
            f"{_NAIF_BASE}/HST/kernels/spk/"
            "hst.bsp"
        ),
    },
    "CHANDRA": {
        "chandra_merged.bsp": (
            f"{_NAIF_BASE}/CHANDRA/kernels/spk/"
            "chandra_merged.bsp"
        ),
    },
    "SPITZER": {
        "spk_030825_200134_220101.bsp": (
            f"{_NAIF_BASE}/SIRTF/kernels/spk/"
            "spk_030825_200134_220101.bsp"
        ),
    },
    "GENESIS": {
        "gns_010811_041125_101231.bsp": (
            f"{_NAIF_BASE}/GNS/kernels/spk/"
            "gns_010811_041125_101231.bsp"
        ),
    },
    "GIOTTO": {
        "giotto_19860305_19860317.bsp": (
            f"{_NAIF_BASE}/GIOTTO/kernels/spk/"
            "giotto_19860305_19860317.bsp"
        ),
    },
    "MARINER_9": {
        "m9.bsp": (
            f"{_NAIF_BASE}/M9/kernels/spk/"
            "m9.bsp"
        ),
    },
    "MARINER_10": {
        "M10_archive_1.bsp": (
            f"{_NAIF_BASE}/M10/kernels/spk/"
            "M10_archive_1.bsp"
        ),
    },
    "VEGA_1": {
        "vega.1-17.04.1984.bsp": (
            f"{_NAIF_BASE}/VEGA/kernels/spk/"
            "vega.1-17.04.1984.bsp"
        ),
    },
    "CONTOUR": {
        "contour.traj.031401.noplephem-2.bsp": (
            f"{_NAIF_BASE}/CONTOUR/kernels/spk/"
            "contour.traj.031401.noplephem-2.bsp"
        ),
    },
    "IUE": {
        "IUE.bsp": (
            f"{_NAIF_BASE}/IUE/kernels/spk/"
            "IUE.bsp"
        ),
    },
    "PIONEER_6": {
        "pio6-a.bsp": (
            f"{_NAIF_BASE}/PIONEER6/kernels/spk/"
            "pio6-a.bsp"
        ),
    },
    "PIONEER_8": {
        "pioneer8-seti.bsp": (
            f"{_NAIF_BASE}/PIONEER8/kernels/spk/"
            "pioneer8-seti.bsp"
        ),
    },
    "LUNAR_ORBITER_1": {
        "lo1_ssd_lp150q.bsp": (
            f"{_NAIF_BASE}/LUNARORBITER/kernels/spk/"
            "lo1_ssd_lp150q.bsp"
        ),
    },
    "LUNAR_ORBITER_2": {
        "lo2_ssd_lp150q.bsp": (
            f"{_NAIF_BASE}/LUNARORBITER/kernels/spk/"
            "lo2_ssd_lp150q.bsp"
        ),
    },
    "LUNAR_ORBITER_3": {
        "lo3_ssd_lp150q.bsp": (
            f"{_NAIF_BASE}/LUNARORBITER/kernels/spk/"
            "lo3_ssd_lp150q.bsp"
        ),
    },
    "LUNAR_ORBITER_4": {
        "lo4_ssd_lp150q_v2.bsp": (
            f"{_NAIF_BASE}/LUNARORBITER/kernels/spk/"
            "lo4_ssd_lp150q_v2.bsp"
        ),
    },
    "LUNAR_ORBITER_5": {
        "lo5_ssd_lp150q.bsp": (
            f"{_NAIF_BASE}/LUNARORBITER/kernels/spk/"
            "lo5_ssd_lp150q.bsp"
        ),
    },
    "INTEGRAL": {
        "integral_sc_ssm_20021017_20250325_v02.bsp": (
            "https://spiftp.esac.esa.int/data/SPICE/INTEGRAL/kernels/spk/"
            "integral_sc_ssm_20021017_20250325_v02.bsp"
        ),
    },
    "GAIA": {
        "gaia_flp_20131219_21250328_v01.bsp": (
            "https://spiftp.esac.esa.int/data/SPICE/GAIA/kernels/spk/"
            "gaia_flp_20131219_21250328_v01.bsp"
        ),
    },
    "EUCLID": {
        "euclid_flp_00077_20230701_20311005_v01.bsp": (
            "https://spiftp.esac.esa.int/data/SPICE/EUCLID/kernels/spk/"
            "euclid_flp_00077_20230701_20311005_v01.bsp"
        ),
    },
    "HERA": {
        "hera_fcp_000067_241007_261104_v01.bsp": (
            "https://spiftp.esac.esa.int/data/SPICE/HERA/kernels/spk/"
            "hera_fcp_000067_241007_261104_v01.bsp"
        ),
    },
    "LADEE": {
        "ladee_r_13250_13279_pha_v01.bsp": (
            f"{_NAIF_BASE}/LADEE/kernels/spk/"
            "ladee_r_13250_13279_pha_v01.bsp"
        ),
        "ladee_r_13278_13325_loa_v01.bsp": (
            f"{_NAIF_BASE}/LADEE/kernels/spk/"
            "ladee_r_13278_13325_loa_v01.bsp"
        ),
        "ladee_r_13325_14108_sci_v01.bsp": (
            f"{_NAIF_BASE}/LADEE/kernels/spk/"
            "ladee_r_13325_14108_sci_v01.bsp"
        ),
        "ladee_r_14108_99001_imp_v01.bsp": (
            f"{_NAIF_BASE}/LADEE/kernels/spk/"
            "ladee_r_14108_99001_imp_v01.bsp"
        ),
    },
}

# Missions with segmented SPK files — each maps to a manifest JSON
# listing individual segment files with time coverage.
SEGMENTED_MISSIONS: dict[str, str] = {
    "CASSINI": "cassini.json",
    "MRO": "mro.json",
    "MARS_2020": "mars2020.json",
    "LRO": "lro.json",
    "LUNAR_PROSPECTOR": "lunar_prospector.json",
    "MGS": "mgs.json",
    "MARS_ODYSSEY": "mars_odyssey.json",
    "STARDUST": "stardust.json",
    "AKATSUKI": "akatsuki.json",
    "GRAIL_A": "grail.json",
    "GRAIL_B": "grail.json",  # Same SPK files contain both spacecraft
    "MAGELLAN": "magellan.json",
    "EXOMARS_TGO": "exomars_tgo.json",
    "CHANDRAYAAN_1": "chandrayaan1.json",
}


# Body IDs actually used in SPK kernel files.
# NAIF reuses IDs across missions and some kernels use non-standard IDs.
# This dict overrides MISSION_NAIF_IDS for SPICE API calls (spkpos, spkezr).
# Only missions where the kernel ID differs from MISSION_NAIF_IDS need entries.
_KERNEL_BODY_IDS: dict[str, int] = {
    "GIOTTO": -78,        # Kernel uses -78, not -20
    "MARINER_10": -76,    # Kernel uses -76 (same as MSL)
    "CONTOUR": -200,      # Kernel uses -200, not -36
    "IUE": -110637,       # Kernel uses -110637, not -43
    "VEGA_1": -66,        # Kernel uses -66, not -11
    "EXOMARS_TGO": -143000,  # COG kernels use -143000, not -143
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_spice_body_id(mission_key: str) -> int:
    """Get the body ID to use in SPICE API calls for a mission.

    Some SPK kernels use different body IDs than the 'official' NAIF assignment.
    This function returns the ID that actually works with the loaded kernel.
    """
    if mission_key in _KERNEL_BODY_IDS:
        return _KERNEL_BODY_IDS[mission_key]
    return MISSION_NAIF_IDS[mission_key]


def has_kernels(mission_key: str) -> bool:
    """Check if a mission has kernel support (single-file or segmented)."""
    return mission_key in MISSION_KERNELS or mission_key in SEGMENTED_MISSIONS

def resolve_mission(name: str) -> tuple[int, str]:
    """Resolve a mission name to (NAIF ID, canonical mission key).

    Performs case-insensitive lookup with alias support.

    Args:
        name: Mission name (e.g., "PSP", "Parker Solar Probe", "ace").

    Returns:
        Tuple of (NAIF integer ID, canonical key string).

    Raises:
        KeyError: If the mission name cannot be resolved.
    """
    key = name.strip().upper().replace("-", "_")

    # Direct match
    if key in MISSION_NAIF_IDS:
        return MISSION_NAIF_IDS[key], key

    # Alias match
    alias_key = _ALIASES.get(key) or _ALIASES.get(name.strip().upper())
    if alias_key and alias_key in MISSION_NAIF_IDS:
        return MISSION_NAIF_IDS[alias_key], alias_key

    # Try without underscores
    compact = key.replace("_", "")
    for canon, naif_id in MISSION_NAIF_IDS.items():
        if canon.replace("_", "") == compact:
            return naif_id, canon

    raise KeyError(
        f"Unknown mission '{name}'. Supported: "
        + ", ".join(sorted(k for k, v in MISSION_NAIF_IDS.items() if v < 0))
    )


def list_supported_missions() -> list[dict]:
    """Return a list of supported missions with NAIF IDs and kernel availability.

    Returns:
        List of dicts with keys: mission_key, naif_id, has_kernels.
    """
    return [
        {
            "mission_key": key,
            "naif_id": naif_id,
            "has_kernels": has_kernels(key),
        }
        for key, naif_id in sorted(MISSION_NAIF_IDS.items())
        if naif_id < 0  # spacecraft only
    ]
