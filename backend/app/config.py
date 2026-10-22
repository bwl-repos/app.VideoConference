from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres@localhost:5432/video_rooms"

    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_url: str = "ws://localhost:7880"          # client-facing (ws/wss)
    livekit_host_url: str = "http://localhost:7880"   # server-side REST

    # Recording storage (S3 / MinIO)
    s3_endpoint: str = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "recordings"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_public_base: str = "http://localhost:9000/recordings"

    # Public URL where the frontend serves the headless recording page
    recording_view_base_url: str = "http://localhost:5173/recording-view"

    cors_origins: str = "*"

    # Tenancy / admin
    default_tenant_slug: str = "openpbl"   # used when no API key is presented (existing app)
    admin_jwt_secret: str = "change-me-admin-secret"   # signs admin panel sessions
    node_secret: str = ""                  # shared secret for node agents → /api/internal/nodes

    # Finance / modelo de custo (Lightsail fixo sa-east-1 + S3 variável).
    # Ajuste se redimensionar instâncias ou mudar de região/preço.
    cost_app_usd: float = 24.0             # bwl-app (medium_3_1: 2 vCPU / 4 GB)
    cost_livekit_usd: float = 44.0         # bwl-livekit (large_3_1: 2 vCPU / 8 GB)
    cost_egress_usd: float = 84.0          # bwl-egress (xlarge_3_1: 4 vCPU / 16 GB)
    cost_s3_per_gb_usd: float = 0.0405     # S3 Standard sa-east-1 (1ª faixa)
    usd_to_brl: float = 5.40               # câmbio para exibição em BRL

    # Integração OpenPBL (SCORM): progresso dos alunos vem do LRS de interações.
    scorm_lrs_url: str = "https://ltiserver.openpbl.ai"   # GET /interaction-events
    scorm_tenant_slugs: str = "openpbl"    # tenants (slug, csv) que têm a integração ativa
    # Segredo que autoriza o POST /realtime/.../release no Scorm (push SSE instantâneo
    # da liberação). Só a webconf o tem → aluno não consegue forjar liberação.
    # DEVE ser igual ao REALTIME_RELEASE_TOKEN da task def do openpbl.Scorm. Vem do env.
    scorm_realtime_release_token: str = ""

    # Aula OpenPBL ao vivo (class-code, liberação de questionários, encerrar
    # registro, chat do facilitador). A webconf replica as chamadas que o pacote
    # PRESENTATION faz. Chaves ficam em env (backend.env no servidor) — nunca no repo.
    openpbl_integration_url: str = "https://integration.openpbl.ai"
    openpbl_integration_apikey: str = ""       # header `apikey` (ContentBuilder)
    openpbl_chat_url: str = "https://chat.openpbl.ai"
    openpbl_chat_user: str = ""                # HTTP Basic do painel do professor
    openpbl_chat_pass: str = ""

    # Avaliação de desempenho na plenária. O facilitador clica com o botão
    # direito na câmera do aluno e dá a nota de participação ali, sem sair da
    # sala; a nota vai para o elearn (Rise), que é onde a conta da planilha
    # vive (`app/services/desempenho_calculo.py` no openbpl.Rise).
    #
    # NÃO é a mesma integração de `openpbl_integration_url`: aquela fala com a
    # API legada (ContentBuilder, PerformanceEvaluation), e o pacote de
    # desempenho novo não mora lá. Mandar a nota para o lugar errado não daria
    # erro -- ela simplesmente não apareceria para o aluno.
    openpbl_rise_url: str = "https://elearnapp.openpbl.ai/api"
    #: Bearer da conta de serviço no elearn. Vem do env (backend.env no
    #: servidor), nunca do repo — mesma regra das chaves acima.
    openpbl_rise_token: str = ""


settings = Settings()
