# ERP Almoxarifado - Politiplastic

**Sistema completo de gestão de estoque desenvolvido e utilizado internamente na Politi Plastic.**

> Reduzi rupturas de estoque em **aproximadamente 30%** com alertas inteligentes, previsão de consumo e integração em tempo real com o dashboard da intranet.

### 🎥 Demo em Vídeo


https://github.com/user-attachments/assets/afbdceeb-e24d-4e35-89a5-d90f461df650


<!-- Cole aqui o link gerado pelo GitHub depois de arrastar o vídeo -->

https://github.com/user-attachments/assets/SEU_LINK_AQUI

## ✨ Principais Funcionalidades

- Cadastro de itens com **fotos comprimidas** armazenadas no SQLite
- Campo de **apelidos** (busca inteligente por nomes alternativos)
- Entrada e **Saída Múltipla** com fotos dinâmicas do responsável e colaborador
- Histórico completo com filtro por item específico + visualização de fotos
- Previsão de consumo baseada em estatística real (média + desvio padrão)
- Status inteligente do estoque (Crítico / Atenção / Normal / Em Compra)
- Backup automático + restauração fácil
- Temas personalizáveis (Claro, Escuro, Azul, Amarelo)
- **Integração em tempo real** com Dashboard da intranet via Socket.io

## 🛠 Tecnologias Utilizadas

- **Python 3** + **PyQt5** (interface desktop)
- **SQLite3** (banco local)
- **Pillow** (compressão de imagens)
- **Requests** (notificação ao dashboard Node.js)

## 🚀 Como Rodar

```bash
# Clone o repositório
git clone https://github.com/void222222/erp-almoxarifado.git
cd erp-almoxarifado

# Instale as dependências
pip install -r requirements.txt

# Execute
python src/almoxarifado.py
