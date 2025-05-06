import streamlit as st
import numpy_financial as npf
import numpy as np
import pandas as pd # Optional: for displaying cash flow table

# Set page configuration
st.set_page_config(layout="wide", page_title="工业园区 E-FinOps 投资分析")

# --- Helper Functions for Calculations ---

# Calculate Weighted Average TOU Grid Price based on annual percentages
def calculate_avg_tou_price(peak_price, valley_price, shoulder_price, peak_perc, valley_perc, shoulder_perc):
     # Ensure percentages sum to 1, handle potential floating point inaccuracies
     total_perc = peak_perc + valley_perc + shoulder_perc
     if total_perc > 0:
         peak_perc /= total_perc
         valley_perc /= total_perc
         shoulder_perc /= total_perc
     else:
         # Default to static price if percentages are zero
         return (peak_price + valley_price + shoulder_price) / 3 # Or handle as error

     return (peak_price * peak_perc) + (valley_price * valley_perc) + (shoulder_price * shoulder_perc)

# Calculate Baseline Annual Cost (Pure Grid, using Avg TOU)
def calculate_baseline_annual_cost(config):
    annual_elec = config['annual_elec_kwh']
    annual_heat = config['annual_heat_kwh']
    annual_cool = config['annual_cool_kwh']
    grid_avg_cop = config['grid_avg_cop']
    grid_avg_eer = config['grid_avg_eer']

    # Total grid energy input needed for baseline to meet all demands
    # Electricity needs grid kWh directly
    # Heat needs Heat Demand / COP_base kWh grid input
    # Cool needs Cool Demand / EER_base kWh grid input
    total_grid_energy_baseline_input = annual_elec + annual_heat / grid_avg_cop + annual_cool / grid_avg_eer

    # Use weighted average TOU price for baseline cost estimation
    avg_tou_price = calculate_avg_tou_price(
        config['grid_price_peak'], config['grid_price_valley'], config['grid_price_shoulder'],
        config['peak_perc'], config['valley_perc'], config['shoulder_perc']
    )

    return total_grid_energy_baseline_input * avg_tou_price

# Calculate Mixed System Metrics (Simplified Model for What-If)
# This function estimates annual generation/consumption and calculates financial metrics
def calculate_mixed_system_metrics(config, st_area, pv_area, hp_capacity_kw, storage_capacity_kwh):
    annual_elec_need = config['annual_elec_kwh']
    annual_heat_need = config['annual_heat_kwh']
    annual_cool_need = config['annual_cool_kwh']
    # Total delivered energy is the sum of needs, which is constant across scenarios
    total_annual_delivered_energy = annual_elec_need + annual_heat_need + annual_cool_need

    if total_annual_delivered_energy == 0:
        return {
            "total_capex": 0, "annual_opex_mixed": 0, "annual_gross_saving": 0,
            "payback_period": "N/A (无能源需求)", "irr": "N/A", "irr_value": -np.inf,
            "npv_value": 0, "cash_flows": [0] * (config['project_lifespan_years'] + 1)
        }


    # --- 1. CAPEX Calculation ---
    capex_st = st_area * config['st_cost_m2']
    # Simplified PV cost based on area, assuming average panel efficiency translates area to kWp
    # A more accurate model would use area to calculate kWp, then cost per kWp
    # Let's add a simple conversion assumption for PV area to effective capacity
    pv_capacity_kwp = pv_area * config['pv_kwh_m2_hr'] / config['pv_annual_太阳小时'] * 1000 # Very rough est: avg_gen_per_hr * peak_hours -> avg_power -> kWp
    # Let's use a simpler CAPEX based directly on Area for this demo as configured
    capex_pv = pv_area * config['pv_cost_m2']

    capex_hp = hp_capacity_kw * config['hp_cost_kw']
    capex_storage = storage_capacity_kwh * config['storage_cost_kwh']
    total_capex = capex_st + capex_pv + capex_hp + capex_storage

    # --- 2. Annual Energy Generation/Provision (Simplified Potential based on installed size) ---
    # Estimate total annual generation based on area and assumed annual effective hours
    annual_st_potential_heat = st_area * config['st_kwh_m2_hr'] * config['st_annual_太阳小时']
    annual_pv_potential_elec = pv_area * config['pv_kwh_m2_hr'] * config['pv_annual_太阳小时']

    # Estimate total annual energy HP can provide if running, capped by potential demand
    # Assume HP can run enough hours to meet demand fraction up to its capacity limits over the year
    # Simplified: Estimate potential annual heat/cool HP can provide based on capacity and assumed operational hours
    # Let's assume HP operates enough to meet *a fraction* of the *potential* demand it's sized for in the year
    # A simple approach: HP capacity * COP/EER * estimated annual operating hours. But this doesn't link to demand.
    # Let's assume HP annual output is related to its capacity, but capped by total demand.
    # Assume HP provides up to its capacity * operational_hours_per_year / COP/EER total delivered energy.
    # Let's use a simplified fraction approach linked to demand.
    # What fraction of *annual* heat/cool demand could the HP capacity *potentially* meet?
    # Estimate max potential delivered energy by HP = HP_capacity_kW * 8760_hours * Average_Utilization_Factor
    # This is hard without profiles. Let's simplify dramatically:
    # Assume HP is sized to meet a fraction of PEAK demand. Annual energy is even harder.
    # Let's link HP potential annual delivery directly to CAPACITY using an assumed total annual run-time factor (e.g., 3000-5000 hrs/year total)
    hp_annual_run_hours = 4000 # Simplified assumption for total run hours over year (heating + cooling)
    hp_potential_delivered_heat = hp_capacity_kw * config['hp_cop'] * (hp_annual_run_hours / 2) # Assume split hours for heat/cool
    hp_potential_delivered_cool = hp_capacity_kw * config['hp_eer'] * (hp_annual_run_hours / 2)

    # Cap the provided energy by the actual annual demand
    annual_pv_supplied = min(annual_pv_potential_elec, annual_elec_need)
    annual_st_supplied_heat = min(annual_st_potential_heat, annual_heat_need)
    annual_hp_supplied_heat = min(hp_potential_delivered_heat, annual_heat_need - annual_st_supplied_heat) # HP supplements ST for heat
    annual_hp_supplied_cool = min(hp_potential_delivered_cool, annual_cool_need)

    # --- 3. Energy Balance & Grid Import (Simplified) ---
    # Calculate energy from each source on the INPUT side for cost calculation
    annual_pv_input_cost = 0 # Assume PV has zero marginal running cost
    annual_st_input_cost = 0 # Assume ST has zero marginal running cost

    # Grid energy input required for HP
    annual_hp_grid_input = (annual_hp_supplied_heat / config['hp_cop']) + (annual_hp_supplied_cool / config['hp_eer'])

    # Remaining demand met by grid (input energy perspective)
    # Remaining electrical demand input = (Total Elec Need - PV Supplied)
    # Remaining heat demand input from grid = (Total Heat Need - ST Supplied - HP Supplied Heat) / Baseline COP
    # Remaining cool demand input from grid = (Total Cool Need - HP Supplied Cool) / Baseline EER
    annual_elec_from_grid = max(0, annual_elec_need - annual_pv_supplied)
    annual_heat_from_grid_input = max(0, annual_heat_need - annual_st_supplied_heat - annual_hp_supplied_heat) / config['grid_avg_cop']
    annual_cool_from_grid_input = max(0, annual_cool_need - annual_hp_supplied_cool) / config['grid_avg_eer']

    # Total grid energy *input* required for mixed system (before storage arbitrage)
    total_grid_input_mixed_pre_storage = annual_elec_from_grid + annual_heat_from_grid_input + annual_cool_from_grid_input + annual_hp_grid_input

    # Annual storage arbitrage potential
    # Simplified: assume storage cycles a certain number of times per year, shifting energy from valley to peak
    # This is a major simplification; real storage value depends heavily on load/generation profiles and TOU structure.
    storage_arbitrage_kwh_year = storage_capacity_kwh * config['storage_cycles_year']
    storage_saving_per_kwh_shifted = (config['grid_price_peak'] - config['grid_price_valley']) # Gross saving per kWh shifted peak vs valley
    # Account for round trip efficiency
    annual_storage_saving = storage_arbitrage_kwh_year * storage_saving_per_kwh_shifted * config['storage_eff_charge'] * config['storage_eff_discharge']


    # Calculate grid cost for mixed system
    avg_tou_price = calculate_avg_tou_price(
        config['grid_price_peak'], config['grid_price_valley'], config['grid_price_shoulder'],
        config['peak_perc'], config['valley_perc'], config['shoulder_perc']
    )
    annual_grid_cost_mixed = total_grid_input_mixed_pre_storage * avg_tou_price - annual_storage_saving
    annual_grid_cost_mixed = max(0, annual_grid_cost_mixed) # Grid cost cannot be negative


    # Annual Operating Expenses (OPEX) for mixed system components
    annual_opex_mixed = total_capex * config['opex_percentage'] # Simplified OPEX as % of total CAPEX

    # Total Annual Operating Cost (before tax/depreciation saving)
    annual_operating_cost_mixed = annual_grid_cost_mixed + annual_opex_mixed

    # --- 4. Financial Metrics Calculation (using After-Tax Cash Flows) ---

    # Annual Gross Saving (Operating Cost Saving compared to baseline)
    baseline_annual_cost_tou = calculate_baseline_annual_cost(config)
    annual_gross_saving = baseline_annual_cost_tou - annual_operating_cost_mixed

    # Calculate cash flows over the project lifespan
    project_lifespan = config['project_lifespan_years']
    depreciation_years = config['depreciation_years']
    tax_rate = config['tax_rate']

    cash_flows = [-total_capex] # CF_0 is initial investment

    for t in range(1, project_lifespan + 1):
        # Depreciation for tax shield
        current_depreciation = total_capex / depreciation_years if depreciation_years > 0 and t <= depreciation_years else 0

        # Annual Cash Flow (After-Tax)
        # Formula: CF_t = (Gross Saving - Depreciation) * (1 - Tax Rate) + Depreciation
        # This correctly accounts for the tax shield from depreciation.
        # Handle case where Gross Saving < Depreciation (taxable income is negative). Assuming tax shield only applies up to the point of reducing taxable income to zero.
        taxable_income_increase = annual_gross_saving - current_depreciation
        tax_amount = max(0, taxable_income_increase) * tax_rate # Tax paid on the positive part of saving after depreciation

        # Net cash flow = Gross Saving - Tax paid
        cf_t = annual_gross_saving - tax_amount
        # The standard formula is often better: CF = (Gross Saving - Deprec) * (1-T) + Deprec = Gross Saving * (1-T) + Deprec * T
        cf_t = annual_gross_saving * (1 - tax_rate) + current_depreciation * tax_rate


        cash_flows.append(cf_t)

    # Payback Period Calculation
    cumulative_cf = np.cumsum(cash_flows)
    payback_period_display = "N/A (未能回本)" # Default if not recovered
    payback_year_num = float('inf')

    if cumulative_cf[-1] >= 0: # Only calculate if project eventually breaks even
        for i in range(1, len(cumulative_cf)):
            if cumulative_cf[i] >= 0 and cumulative_cf[i-1] < 0:
                payback_year_num = i - 1 + abs(cumulative_cf[i-1]) / cash_flows[i]
                payback_period_display = f"{payback_year_num:.2f} 年"
                break
        if payback_year_num == float('inf') and cumulative_cf[0] < 0 and cumulative_cf[1] >= 0: # Case where break even in year 1
             payback_year_num = abs(cash_flows[0]) / cash_flows[1] if cash_flows[1] > 0 else float('inf')
             payback_period_display = f"{payback_year_num:.2f} 年" if payback_year_num != float('inf') else "N/A (第一年现金流不足)"
        elif payback_year_num == float('inf') and cumulative_cf[0] >=0: # Case where already cash flow positive from start (unlikely with CAPEX)
             payback_period_display = "即时" # Or 0 years


    # IRR Calculation
    irr_value = -np.inf # Default to very low value
    irr_display = "N/A (无法计算IRR)"
    
    # Add debugging output
    st.write("Debug: Cash flows:", cash_flows)
    
    # np.irr requires cash flows to contain both positive and negative values
    if cash_flows[0] < 0:  # Ensure initial investment is negative
        try:
            # Check if we have any positive cash flows
            if any(cf > 0 for cf in cash_flows[1:]):
                # Use numpy financial's IRR calculation
                irr_value = npf.irr(cash_flows)
                if not np.isnan(irr_value) and not np.isinf(irr_value):
                    irr_display = f"{irr_value*100:.2f} %"
                else:
                    irr_display = "N/A (IRR计算结果无效)"
            else:
                irr_display = "N/A (无正现金流)"
        except Exception as e:
            irr_display = f"N/A (IRR计算错误: {str(e)})"
            
    else:
        irr_display = "N/A (初始投资应为负值)"

    # NPV Calculation (using the defined discount rate)    
    npv_value = npf.npv(config['discount_rate'], cash_flows)



    return {
        "total_capex": total_capex,
        "annual_opex_mixed": annual_opex_mixed,
        "annual_gross_saving": annual_gross_saving, # Saving vs baseline operating cost (pre-tax/deprec)
        "payback_period": payback_period_display,
        "payback_year_num": payback_year_num, # Numerical for optimization
        "irr": irr_display,
        "irr_value": irr_value, # Numerical for optimization
        "npv_value": npv_value, # Numerical for optimization
        "cash_flows": cash_flows # Full cash flow series
    }

# --- Configuration Tab ---
def config_page():
    st.title("⚙️ E-FinOps 配置页面")
    st.write("请在此配置工业园区能源需求、市电参数和太阳雨牌牌设备的性能成本参数。")
    st.write("---")

    # Use session state for persistent configuration
    if 'config' not in st.session_state:
        # Set reasonable default values
        st.session_state.config = {
            'annual_elec_kwh': 10_000_000,
            'annual_heat_kwh': 5_000_000,
            'annual_cool_kwh': 3_000_000,

            'grid_price_static': 0.8, # 元/kWh
            'grid_price_peak': 1.2,   # 元/kWh
            'grid_price_valley': 0.5, # 元/kWh
            'grid_price_shoulder': 0.8, # 元/kWh
            'peak_perc': 0.20, # 20%
            'valley_perc': 0.35, # 35%
            # shoulder_perc derived as 1 - peak - valley

            'grid_avg_cop': 2.5, # Baseline electric heating/cooling efficiency
            'grid_avg_eer': 3.5,

            'st_kwh_m2_hr': 0.5, # kWh/m²/hr
            'st_cost_m2': 1500.0, # 元/m²
            'st_annual_太阳小时': 1500, # Annual effective solar hours for thermal

            'pv_kwh_m2_hr': 0.15, # kWh/m²/hr (average generation rate)
            'pv_cost_m2': 1000.0, # 元/m² (simplified cost per area)
            'pv_annual_太阳小时': 1200, # Annual effective solar hours for PV (considers capacity factor)

            'hp_cop': 4.0, # Heat pump COP
            'hp_eer': 5.0, # Heat pump EER
            'hp_cost_kw': 2000.0, # 元/kW (cost per kW heating/cooling capacity)

            'storage_eff_charge': 0.95, # 95%
            'storage_eff_discharge': 0.95, # 95%
            'storage_cost_kwh': 1500.0, # 元/kWh
            'storage_cycles_year': 300, # Equivalent full cycles per year for arbitrage

            'project_lifespan_years': 20, # Years
            'opex_percentage': 0.015, # 1.5% of CAPEX per year
            'tax_rate': 0.25, # 25%
            'discount_rate': 0.08, # 8% Hurdle Rate / Discount Rate
            'depreciation_years': 10 # Fixed by tax law for assets > 10 years
        }

    st.header("1. 园区年能源需求 (总计)")
    st.session_state.config['annual_elec_kwh'] = st.number_input("年总用电需求 (kWh/年)", value=st.session_state.config['annual_elec_kwh'], min_value=0, step=10000)
    st.session_state.config['annual_heat_kwh'] = st.number_input("年总用热需求 (kWh 热量/年)", value=st.session_state.config['annual_heat_kwh'], min_value=0, step=10000)
    st.session_state.config['annual_cool_kwh'] = st.number_input("年总用冷需求 (kWh 冷量/年)", value=st.session_state.config['annual_cool_kwh'], min_value=0, step=10000)

    st.header("2. 市电参数")
    col_grid1, col_grid2 = st.columns(2)
    with col_grid1:
        st.session_state.config['grid_price_static'] = st.number_input("市电静态单价 (元/kWh)", value=st.session_state.config['grid_price_static'], min_value=0.0, format="%.3f")
        st.session_state.config['grid_price_peak'] = st.number_input("市电峰时段单价 (元/kWh)", value=st.session_state.config['grid_price_peak'], min_value=0.0, format="%.3f")
        st.session_state.config['grid_price_valley'] = st.number_input("市电谷时段单价 (元/kWh)", value=st.session_state.config['grid_price_valley'], min_value=0.0, format="%.3f")
        st.session_state.config['grid_price_shoulder'] = st.number_input("市电平时段单价 (元/kWh)", value=st.session_state.config['grid_price_shoulder'], min_value=0.0, format="%.3f")
    with col_grid2:
        st.session_state.config['peak_perc'] = st.number_input("峰时段占全年小时比例 (%)", value=st.session_state.config['peak_perc']*100, min_value=0.0, max_value=100.0, format="%.1f") / 100
        st.session_state.config['valley_perc'] = st.number_input("谷时段占全年小时比例 (%)", value=st.session_state.config['valley_perc']*100, min_value=0.0, max_value=100.0, format="%.1f") / 100
        # Calculate shoulder perc dynamically
        derived_shoulder_perc = 1.0 - st.session_state.config['peak_perc'] - st.session_state.config['valley_perc']
        st.session_state.config['shoulder_perc'] = max(0.0, derived_shoulder_perc) # Ensure it's not negative due to input errors
        if derived_shoulder_perc < -1e-9: # Allow small floating point errors
             st.warning("峰谷时段比例之和超过100%。请检查输入。")
        st.write(f"计算得平时段占全年小时比例: **{st.session_state.config['shoulder_perc']*100:.1f} %**")

    st.session_state.config['grid_avg_cop'] = st.number_input("市电制热平均COP (用于基线)", value=st.session_state.config['grid_avg_cop'], min_value=1.0, format="%.2f")
    st.session_state.config['grid_avg_eer'] = st.number_input("市电制冷平均EER (用于基线)", value=st.session_state.config['grid_avg_eer'], min_value=1.0, format="%.2f")


    st.header("3. 太阳雨牌设备参数")
    col_sr1, col_sr2 = st.columns(2)
    with col_sr1:
        st.subheader("光热集热器")
        st.session_state.config['st_kwh_m2_hr'] = st.number_input("平均集热量 (kWh/m²/hr)", value=st.session_state.config['st_kwh_m2_hr'], min_value=0.01, format="%.2f")
        st.session_state.config['st_cost_m2'] = st.number_input("每平米成本 (元/m²)", value=st.session_state.config['st_cost_m2'], min_value=100.0, step=100.0)
        st.session_state.config['st_annual_太阳小时'] = st.number_input("年有效太阳小时数 (用于热量估算)", value=st.session_state.config['st_annual_太阳小时'], min_value=100, step=50)

        st.subheader("热泵/冷机")
        st.session_state.config['hp_cop'] = st.number_input("平均COP (制热)", value=st.session_state.config['hp_cop'], min_value=1.0, format="%.2f")
        st.session_state.config['hp_eer'] = st.number_input("平均EER (制冷)", value=st.session_state.config['hp_eer'], min_value=1.0, format="%.2f")
        st.session_state.config['hp_cost_kw'] = st.number_input("每kW容量成本 (元/kW)", value=st.session_state.config['hp_cost_kw'], min_value=100.0, step=100.0)

    with col_sr2:
        st.subheader("光伏阵列")
        st.session_state.config['pv_kwh_m2_hr'] = st.number_input("平均发电量 (kWh/m²/hr)", value=st.session_state.config['pv_kwh_m2_hr'], min_value=0.001, format="%.3f")
        st.session_state.config['pv_cost_m2'] = st.number_input("每平米成本 (元/m²)", value=st.session_state.config['pv_cost_m2'], min_value=100.0, step=100.0)
        st.session_state.config['pv_annual_太阳小时'] = st.number_input("年有效发电小时数 (用于发电量估算)", value=st.session_state.config['pv_annual_太阳小时'], min_value=100, step=50)


        st.subheader("储能系统")
        st.session_state.config['storage_eff_charge'] = st.number_input("充电效率 (%)", value=st.session_state.config['storage_eff_charge']*100, min_value=0.0, max_value=100.0, format="%.1f") / 100
        st.session_state.config['storage_eff_discharge'] = st.number_input("放电效率 (%)", value=st.session_state.config['storage_eff_discharge']*100, min_value=0.0, max_value=100.0, format="%.1f") / 100
        st.session_state.config['storage_cost_kwh'] = st.number_input("每kWh容量成本 (元/kWh)", value=st.session_state.config['storage_cost_kwh'], min_value=100.0, step=100.0)
        st.session_state.config['storage_cycles_year'] = st.number_input("年等效循环次数 (用于储能套利估算)", value=st.session_state.config['storage_cycles_year'], min_value=0, step=10)


    st.header("4. 经济参数")
    col_eco1, col_eco2 = st.columns(2)
    with col_eco1:
        st.session_state.config['project_lifespan_years'] = st.number_input("项目生命周期 (年)", value=st.session_state.config['project_lifespan_years'], min_value=10, step=1)
        st.session_state.config['opex_percentage'] = st.number_input("年运维费用占总CAPEX比例 (%)", value=st.session_state.config['opex_percentage']*100, min_value=0.0, max_value=10.0, format="%.2f") / 100
        st.session_state.config['tax_rate'] = st.number_input("企业所得税率 (%)", value=st.session_state.config['tax_rate']*100, min_value=0.0, max_value=100.0, format="%.1f") / 100
    with col_eco2:
        st.session_state.config['discount_rate'] = st.number_input("折现率 / 基准收益率 (%)", value=st.session_state.config['discount_rate']*100, min_value=0.1, max_value=30.0, format="%.1f") / 100
        st.session_state.config['depreciation_years'] = st.number_input("固定资产折旧年限 (年)", value=st.session_state.config['depreciation_years'], min_value=1, max_value=30, step=1)
        if st.session_state.config['depreciation_years'] < 1:
             st.session_state.config['depreciation_years'] = 1 # Avoid division by zero


    st.write("---")
    st.info("参数已保存。请切换到 'What if 投资分析' 页面进行模拟和优化。")


# --- What If Analysis Tab ---
def whatif_page():
    st.title("📊 E-FinOps What if 投资分析")
    st.write("通过调整滑块，实时查看不同设备组合对成本节约和投资回报的影响。")
    st.write("---")

    # Ensure config is loaded
    if 'config' not in st.session_state:
        st.warning("请先在 '配置页面' 完成参数设置。")
        return

    config = st.session_state.config

    # --- Display园区Demand ---
    st.subheader("园区年能源需求总览")
    col_demand1, col_demand2, col_demand3 = st.columns(3)
    col_demand1.metric("用电需求", f"{config['annual_elec_kwh']:,.0f} kWh")
    col_demand2.metric("用热需求", f"{config['annual_heat_kwh']:,.0f} kWh")
    col_demand3.metric("用冷需求", f"{config['annual_cool_kwh']:,.0f} kWh")
    st.write("---")

    # --- Display Baseline ---
    baseline_annual_cost = calculate_baseline_annual_cost(config)
    st.subheader("基线方案 (纯市电供能，考虑峰谷电价和基础电制热/冷效率)")
    st.metric("预计年总成本 (运营成本)", f"¥{baseline_annual_cost:,.2f}")
    st.write("---")

    # --- What If Sliders ---
    st.subheader("混合供能方案配置 (通过滑块调整设备规模)")

    # Initialize slider values in session state if not already present
    if 'sliders' not in st.session_state:
        st.session_state.sliders = {
            'st_area': 0.0,
            'pv_area': 0.0,
            'hp_capacity_kw': 0.0,
            'storage_capacity_kwh': 0.0,
        }

    col_sliders1, col_sliders2 = st.columns(2)

    with col_sliders1:
        st.markdown("#### 太阳雨牌光热集热器")
        st.session_state.sliders['st_area'] = st.slider(
            "安装面积 (m²)", 0.0, 5000.0, st.session_state.sliders['st_area'], 50.0,
            key='st_area_slider', help=f"每平米成本: ¥{config['st_cost_m2']:,.0f}"
        )

        st.markdown("#### 太阳雨牌热泵/冷机")
        st.session_state.sliders['hp_capacity_kw'] = st.slider(
            "总制热/冷容量 (kW)", 0.0, 2000.0, st.session_state.sliders['hp_capacity_kw'], 10.0,
            key='hp_kw_slider', help=f"每kW容量成本: ¥{config['hp_cost_kw']:,.0f}"
        )

    with col_sliders2:
        st.markdown("#### 太阳雨牌光伏阵列")
        st.session_state.sliders['pv_area'] = st.slider(
            "安装面积 (m²)", 0.0, 10000.0, st.session_state.sliders['pv_area'], 100.0,
            key='pv_area_slider', help=f"每平米成本: ¥{config['pv_cost_m2']:,.0f}"
        )

        st.markdown("#### 太阳雨牌储能系统")
        st.session_state.sliders['storage_capacity_kwh'] = st.slider(
            "总储能容量 (kWh)", 0.0, 5000.0, st.session_state.sliders['storage_capacity_kwh'], 50.0,
            key='storage_kwh_slider', help=f"每kWh容量成本: ¥{config['storage_cost_kwh']:,.0f}"
        )

    st.write("---")

    # --- Calculate and Display Metrics for Current Configuration ---
    st_area = st.session_state.sliders['st_area']
    pv_area = st.session_state.sliders['pv_area']
    hp_capacity_kw = st.session_state.sliders['hp_capacity_kw']
    storage_capacity_kwh = st.session_state.sliders['storage_capacity_kwh']

    mixed_metrics = calculate_mixed_system_metrics(
        config, st_area, pv_area, hp_capacity_kw, storage_capacity_kwh
    )

    st.subheader("混合供能方案效果")
    col_metrics1, col_metrics2, col_metrics3 = st.columns(3)

    col_metrics1.metric("总投资 (CAPEX)", f"¥{mixed_metrics['total_capex']:,.0f}") # Display CAPEX as integer
    col_metrics2.metric("预计年总运维费用 (OPEX)", f"¥{mixed_metrics['annual_opex_mixed']:,.0f}")
    col_metrics3.metric("预计年总成本节约 (对比基线运营成本，税前)", f"¥{mixed_metrics['annual_gross_saving']:,.0f}")

    col_metrics4, col_metrics5 = st.columns(2)
    with col_metrics4:
         st.metric("投资回收期 (考虑税盾，税后现金流)", mixed_metrics['payback_period'])
    with col_metrics5:
         st.metric("内部收益率 (IRR)", mixed_metrics['irr'])
         st.write(f"<sub>基准收益率/折现率: {config['discount_rate']*100:.1f}%</sub>", unsafe_allow_html=True)

    # Optional: Display cash flow table in an expander
    with st.expander("查看详细年度现金流量预测 (税后)"):
        cf_df = pd.DataFrame({'年份': range(len(mixed_metrics['cash_flows'])), '现金流量 (¥)': mixed_metrics['cash_flows']})
        st.dataframe(cf_df.style.format({'现金流量 (¥)': '{:,.2f}'}))
        st.write("<sub>注: 0年份为初始投资CAPEX，后续年份为年度净现金流入。折旧税盾在折旧年限内生效。</sub>", unsafe_allow_html=True)

    st.write("---")

    # --- Optimization Section ---
    st.subheader("方案优化")
    optimization_strategy = st.radio(
        "选择优化策略:",
        ('最大化内部收益率 (IRR)', '最小化投资回收期 (Payback Period)', '最大化净现值 (NPV)'),
        index=0, # Default to Maximize IRR
        horizontal=True
    )
    st.write("<sub>注: 优化计算采用简化模型和网格搜索，结果为近似最优。计算量可能与滑块范围和步长有关。</sub>", unsafe_allow_html=True)


    if st.button("🔎 查找最优方案", use_container_width=True):
        st.info(f"正在执行优化计算，策略: {optimization_strategy}...")

        # --- Optimization Logic (Simple Grid Search) ---
        # Define the objective function based on the strategy
        def objective_function(params):
            # params = [st_area, pv_area, hp_capacity_kw, storage_capacity_kwh]
            # Ensure non-negative values, round to slider steps for grid search consistency
            rounded_params = [
                round(params[0] / 50.0) * 50.0,    # st_area step 50
                round(params[1] / 100.0) * 100.0,  # pv_area step 100
                round(params[2] / 10.0) * 10.0,    # hp_capacity_kw step 10
                round(params[3] / 50.0) * 50.0,    # storage_capacity_kwh step 50
            ]
            # Ensure within slider bounds
            rounded_params[0] = np.clip(rounded_params[0], 0.0, 5000.0)
            rounded_params[1] = np.clip(rounded_params[1], 0.0, 10000.0)
            rounded_params[2] = np.clip(rounded_params[2], 0.0, 2000.0)
            rounded_params[3] = np.clip(rounded_params[3], 0.0, 5000.0)

            metrics = calculate_mixed_system_metrics(config, *rounded_params)

            if optimization_strategy == '最大化内部收益率 (IRR)':
                # Return -IRR value (minimize negative IRR = maximize IRR). Penalize non-calculable IRRs. 
                # return -metrics['irr_value'] if metrics['irr_value'] != -np.inf else np.inf
                # Change the penalty to a large negative number (e.g., -1e9) instead of np.inf. 
                # This way, the optimizer will still prefer solutions with calculable IRR, but it won't completely disregard solutions where IRR cannot be calculated, 
                # allowing it to explore a wider range of possibilities
                # return -metrics['irr_value'] if metrics['irr_value'] != -np.inf else -1e9
                return metrics['irr_value'] if metrics['irr_value'] != -np.inf else -1e9
            
            
            elif optimization_strategy == '最小化投资回收期 (Payback Period)':
                 # Return numerical payback period. Penalize non-recovered projects.
                 return metrics['payback_year_num'] if metrics['payback_year_num'] != float('inf') else config['project_lifespan_years'] * 2 # Penalize non-recovery

            elif optimization_strategy == '最大化净现值 (NPV)':
                # Return -NPV (minimize negative NPV = maximize NPV)
                return -metrics['npv_value']


        # Define steps for grid search (using fewer steps for faster demo)
        # Adjust these ranges and steps for more precision vs speed
        st_steps_opt = np.linspace(0, 5000, 6) # 0, 1000, 2000, 3000, 4000, 5000
        pv_steps_opt = np.linspace(0, 10000, 6) # 0, 2000, 4000, ... 10000
        hp_steps_opt = np.linspace(0, 2000, 6)  # 0, 400, 800, ... 2000
        storage_steps_opt = np.linspace(0, 5000, 6) # 0, 1000, 2000, ... 5000

        best_objective_value = float('inf') if '最小化' in optimization_strategy else float('-inf')
        best_params = None

        # Simple Grid Search Loop
        progress_text = "优化中，请稍候..."
        my_bar = st.progress(0, text=progress_text)
        total_iterations = len(st_steps_opt) * len(pv_steps_opt) * len(hp_steps_opt) * len(storage_steps_opt)
        i = 0

        for s_area in st_steps_opt:
            for p_area in pv_steps_opt:
                for h_cap in hp_steps_opt:
                    for stor_cap in storage_steps_opt:
                        current_params = [s_area, p_area, h_cap, stor_cap]

                        # Calculate objective value (handle potential errors)
                        try:
                            current_objective_value = objective_function(current_params)
                            
                            st.write(f"Params: {current_params}, Objective: {current_objective_value}")

                            if '最小化' in optimization_strategy:
                                if current_objective_value < best_objective_value:
                                    best_objective_value = current_objective_value
                                    best_params = current_params
                            elif '最大化' in optimization_strategy:
                                 if current_objective_value > best_objective_value:
                                    best_objective_value = current_objective_value
                                    best_params = current_params

                        except Exception as e:
                            # print(f"Error calculating metrics for {current_params}: {e}") # Debugging
                            pass # Skip combinations that cause calculation errors (e.g. division by zero if demand is 0 but capacity isn't)


                        i += 1
                        my_bar.progress(i / total_iterations, text=progress_text)

        my_bar.empty() # Hide progress bar when done


        if best_params:
            st.success("✅ 找到近似最优方案！")
            # Update sliders to optimal values using session state
            st.session_state.sliders['st_area'] = float(best_params[0])
            st.session_state.sliders['pv_area'] = float(best_params[1])
            st.session_state.sliders['hp_capacity_kw'] = float(best_params[2])
            st.session_state.sliders['storage_capacity_kwh'] = float(best_params[3])

            # Recalculate metrics for the best params to display them clearly below
            optimal_metrics = calculate_mixed_system_metrics(config, *best_params)

            st.write("**🏆 近似最优方案配置:**")
            
            optimal_metrics_irr = calculate_mixed_system_metrics(config, *best_params)
            st.write("IRR Cash Flows:", optimal_metrics_irr['cash_flows'])
            
            st.write(f"- 光热集热器面积: **{best_params[0]:,.0f}** m²")
            st.write(f"- 光伏阵列面积: **{best_params[1]:,.0f}** m²")
            st.write(f"- 热泵/冷机容量: **{best_params[2]:,.0f}** kW")
            st.write(f"- 储能系统容量: **{best_params[3]:,.0f}** kWh")

            st.write("**📈 该最优方案的投资回报指标:**")
            col_opt_metrics1, col_opt_metrics2, col_opt_metrics3 = st.columns(3)
            col_opt_metrics1.metric("总投资 (CAPEX)", f"¥{optimal_metrics['total_capex']:,.0f}")
            col_opt_metrics2.metric("预计年总运维费用 (OPEX)", f"¥{optimal_metrics['annual_opex_mixed']:,.0f}")
            col_opt_metrics3.metric("预计年总成本节约 (税前)", f"¥{optimal_metrics['annual_gross_saving']:,.0f}")

            col_opt_metrics4, col_opt_metrics5 = st.columns(2)
            with col_opt_metrics4:
                 st.metric("投资回收期:", optimal_metrics['payback_period'])
            with col_opt_metrics5:
                 st.metric("内部收益率 (IRR):", optimal_metrics['irr'])


            # Trigger a rerun to update the sliders and the main metrics display above
            st.rerun()

        else:
            st.warning("未能找到有效的近似最优方案。请检查配置参数、滑块范围或尝试不同的优化策略。")

# --- Add image ---
# The image path 'D:\ChrisH\Pictures\total_energy_solution.png' is local.
# For a web app, you'd typically use a URL or embed it.
# As a placeholder, I'll add markdown text indicating where the image belongs conceptually.
# If you deploy this, replace the markdown with actual image code using st.image()
st.sidebar.image("total_energy_solution.png")
# --- Main App Navigation ---
st.sidebar.title("导航")
page = st.sidebar.radio("", ["配置页面", "What if 投资分析页面"])

st.sidebar.markdown("---")
st.sidebar.header("关于")
st.sidebar.markdown(
    """
    **工业园区能耗财务运营框架 (E-FinOps)**
    优化混合供能组合及成本管理

    基于 [FinOps Foundation Framework](https://www.finops.org/) 理念应用于能源领域。

    **免责声明:** 本应用基于简化模型进行估算，仅供概念演示和初步分析参考，非精确工程计算结果。
    """
)



if page == "配置页面":
    config_page()
else:
    whatif_page()
