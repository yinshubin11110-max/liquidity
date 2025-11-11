PWP Submission Package
==========================

Steps to reproduce main results (run inside this folder):

1. py -m venv .venv
2. .venv\Scripts\activate
3. pip install pandas numpy statsmodels scipy matplotlib
4. python src/pwp_data_check.py --panel data/pwp_monthly_panel.csv
5. python src/pwp_event_cs.py --panel data/pwp_monthly_panel.csv --kmin -9 --kmax 9 --baseline -1
6. python src/pwp_event_amihud.py --panel data/pwp_monthly_panel.csv --kmin -9 --kmax 9 --baseline -1
7. python src/pwp_stackeddid.py --panel data/pwp_monthly_panel.csv --y cs_spread --kmin -9 --kmax 9 --baseline -1
8. python src/pwp_stackeddid.py --panel data/pwp_monthly_panel.csv --y amihud --kmin -9 --kmax 9 --baseline -1
9. python src/pwp_primary_median_effect.py --panel data/pwp_monthly_panel.csv --pre -3 -1 --post 0 3
10. python src/pwp_primary_median_boot.py --panel data/pwp_monthly_panel.csv --pre -3 -1 --post 0 3 --B 10000 --seed 42
11. python src/pwp_econ_magnitude.py --panel data/pwp_monthly_panel.csv --pre -3 -1 --post 0 3
12. python src/pwp_power_mde_stack.py --panel data/pwp_monthly_panel.csv --y cs_spread --min -0.30 --max 0.0 --steps 31 --kmin -9 --kmax 9 --baseline -1
13. python src/pwp_plot_power.py --input results/power_curve_cs_stack.csv --output results/fig_power_curve_cs_stack.png --title "Power curve (stacked DID, cs_spread)"

Generated figures/tables appear in results/ and tables/.
