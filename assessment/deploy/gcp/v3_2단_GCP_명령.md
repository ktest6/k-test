# v3 2단 학습을 GCP `stt-lora`(L4 24GB)에서 돌리기 (2026-08-30, RunPod 잔액 소진으로 대체)

주의 셋: ① 이 VM은 시연 서버다 — 학습 중 채점이 느려질 수 있으니 시험 중엔 돌리지 않는다. ② 시연용 venv(`/opt/ktest/venv-stt`)는 **건드리지 않고** 학습용 venv를 따로 만든다(라이브러리 판이 바뀌면 받아쓰기 서버가 깨진다). ③ 브라우저 SSH는 끊길 수 있으니 학습은 `nohup`으로 띄운다.

## 1. 파일 받기 (브라우저 업로드 대신 runpodctl 전송 — RunPod 계정 필요 없음)
VM:
```bash
cd ~ && wget -q https://github.com/runpod/runpodctl/releases/latest/download/runpodctl-linux-amd64 -O ~/runpodctl && chmod +x ~/runpodctl && ~/runpodctl version
```
내 PC PowerShell:
```powershell
D:\해커톤데이터\tools\runpodctl.exe send D:\해커톤데이터\workbench_v3.tar.gz
```
→ 뜨는 `runpodctl receive 1234-word-word-word` 줄에서 **코드만** 가져와 VM에서:
```bash
cd ~ && ~/runpodctl receive <코드>
ls -l ~/workbench_v3.tar.gz     # 1452877053 이어야 함
```

## 2. 학습용 환경 (한 번만, 5~10분)
```bash
python3.11 -m venv ~/train-venv && source ~/train-venv/bin/activate
pip install -q --upgrade pip
pip install -q torch --index-url https://download.pytorch.org/whl/cu124
mkdir -p ~/work && tar xzf ~/workbench_v3.tar.gz -C ~/work ktest_workbench/assessment/deploy/runpod/runpod_setup.sh
bash ~/work/ktest_workbench/assessment/deploy/runpod/runpod_setup.sh --tar ~/workbench_v3.tar.gz --root ~/work --light
```
끝에 `cuda 쓸 수 있나? True` · 카드 `NVIDIA L4` 가 나와야 한다.

## 3. 학습 (nohup — 창이 끊겨도 계속 돈다)
```bash
source ~/train-venv/bin/activate
cd ~/work/ktest_workbench/data
nohup python ../assessment/scripts/speech_lab/train_lora.py \
    --data ../extra/v3_extra/team2000_train_stage2.jsonl \
    --init-adapter ../extra/v3_extra/adapters/v2 \
    --lr 3e-6 --epochs 1 --batch 8 \
    --out ~/adapters/v3-stage2 > ~/train_v3.log 2>&1 &
sleep 60 && grep -m1 "어댑터 얹는 중" ~/train_v3.log && tail -3 ~/train_v3.log
```
- `이어서 배울 어댑터 얹는 중` 이 안 보이면 `pkill -f train_lora.py` 로 멈추고 보고.
- 진행 보기: `tail -f ~/train_v3.log` (Ctrl+C 로 보기만 끝냄, 학습은 계속). 메모리 보기: `nvidia-smi`.
- 시연 서버가 느려지면 `--batch 4` 로 다시.

## 4. 끝난 뒤
```bash
ls ~/adapters/v3-stage2                      # adapter_model.safetensors 가 있어야 함
tar -czf ~/v3-stage2.tar.gz -C ~/adapters v3-stage2 && ~/runpodctl send ~/v3-stage2.tar.gz
```
→ 내 PC `cd D:\해커톤데이터\adapters; D:\해커톤데이터\tools\runpodctl.exe receive <코드>`.
어댑터는 VM에도 남으니(`~/adapters/v3-stage2`) 평가 후 시연에 쓸 땐 `/opt/ktest/adapters/v3`로 복사만 하면 된다. VM은 시연 서버라 끄지 않는다.

정직 표시: `<verbatim>` 태그·오류 토큰 가중은 미적용(축소판).
