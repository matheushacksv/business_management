<script setup lang="ts">
import { pt_br } from '@nuxt/ui/locale'
</script>

<template>
  <!-- pt_br: built-in component texts ("Criar …", "Sem dados", pagination, search...) in Portuguese -->
  <UApp :locale="pt_br" :toaster="{ position: 'top-right' }">
    <NuxtRouteAnnouncer />
    <NuxtLayout>
      <NuxtPage />
    </NuxtLayout>
  </UApp>
</template>
