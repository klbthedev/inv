find ethiopian_einvoice_core -type f ! -path "*/__pycache__/*" ! -name "*.pyc" | sort | xargs sha512sum > ethiopian_einvoice_core.sha512
