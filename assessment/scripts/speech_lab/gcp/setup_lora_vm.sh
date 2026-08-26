#!/usr/bin/env bash
# GCP VM(Deep Learning on Linux, L4) 에서 LoRA 받아쓰기 서버를 처음 세팅하는 스크립트.
# 로컬 lora-venv(torch 2.6.0+cu124 · transformers 4.48.3 · peft 0.14.0)와 같은 판으로 맞춘다.
# (librosa 만 0.11 — VM 파이썬이 3.10 이라 1.0 이 안 깔린다. 기능 차이 없음)
#
# 쓰는 법 (VM 의 SSH 창에서):
#   1) 브라우저 SSH 의 "파일 업로드" 로 이 파일 + lora_stt_server.py + v2_adapter.tar.gz 를 올린다
#   2) bash setup_lora_vm.sh
#   3) 끝나면 화면에 나온 대로 서버를 켠다
set -e
cd ~
sudo apt install -y python3.10-venv   # venv 부품(Deep Learning 이미지에 빠져 있음)
mkdir -p adapters/v2 hf_cache
[ -f v2_adapter.tar.gz ] && tar -xzf v2_adapter.tar.gz -C adapters/v2
# checkpoint-* 는 학습 중간 저장본이므로 제외하고 최종 어댑터 폴더만 잡는다
ADIR=$(dirname "$(find ~/adapters -name adapter_config.json -not -path "*checkpoint*" | head -1)")
echo "어댑터 폴더: $ADIR"

python3 -m venv ~/lora-venv
source ~/lora-venv/bin/activate
pip install -q --upgrade pip
pip install -q torch==2.6.0 --index-url https://download.pytorch.org/whl/cu124
pip install -q transformers==4.48.3 peft==0.14.0 accelerate==1.14.0 \
  librosa==0.11.0 soundfile==0.14.0 fastapi uvicorn httpx python-multipart

python - <<'PY'
import torch; print("GPU:", torch.cuda.get_device_name(0), "| cuda ok:", torch.cuda.is_available())
PY

cat > ~/run_lora.sh <<RUN
#!/usr/bin/env bash
source ~/lora-venv/bin/activate
export HF_HOME=~/hf_cache
export LORA_ADAPTER_DIR=$ADIR
cd ~
nohup python lora_stt_server.py --port 8100 > lora.log 2>&1 &
echo "켜짐. 로그: tail -f ~/lora.log"
RUN
chmod +x ~/run_lora.sh
echo
echo "세팅 끝. 서버 켜기:  ~/run_lora.sh"
echo "확인:              curl localhost:8100/health"
