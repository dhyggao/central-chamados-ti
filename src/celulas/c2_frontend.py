# CÉLULA 2 · SISTEMA DENTRO DO COLAB: abre a página com os três acessos aqui no notebook
# (é a mesma página do link; tudo passa pelo backend Python e pelo Firebase)
from google.colab import output
output.serve_kernel_port_as_iframe(PORTA, path="/", height=1150)
