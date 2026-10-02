/**
 * Exporta a agenda para o arquivo meeting-tracker-agenda.json no seu Google Drive.
 * O tracker lê esse arquivo pela pasta do Google Drive para desktop.
 *
 * Instalação (uma vez):
 *   1. script.google.com > Novo projeto > cole este código
 *   2. Barra da esquerda: "Serviços" (+) > Google Calendar API > Adicionar
 *   3. Escolha a função "instalar" no topo e clique em Executar (autorize o acesso)
 */
const ARQUIVO = 'meeting-tracker-agenda.json';
const DIAS_PASSADOS = 400;

function instalar() {
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('exportar').timeBased().everyHours(1).create();
  exportar();
}

function exportar() {
  const inicio = new Date(Date.now() - DIAS_PASSADOS * 864e5);
  const fim = new Date(Date.now() + 864e5);
  const eventos = [];
  let pageToken;
  do {
    const r = Calendar.Events.list('primary', {
      timeMin: inicio.toISOString(), timeMax: fim.toISOString(),
      singleEvents: true, orderBy: 'startTime', maxResults: 2500, pageToken,
    });
    (r.items || []).forEach(e => {
      if (!e.start || !e.start.dateTime || e.status === 'cancelled') return;  // dia inteiro / cancelado
      const eu = (e.attendees || []).find(a => a.self);
      const meet = e.hangoutLink || ((e.conferenceData || {}).entryPoints || []).map(p => p.uri).join(' ');
      const code = (meet + ' ' + (e.location || '') + ' ' + (e.description || '')).match(/meet\.google\.com\/([a-z]{3}-[a-z]{4}-[a-z]{3})/);
      eventos.push({
        title: e.summary || '',
        start: e.start.dateTime,
        end: e.end.dateTime,
        code: code ? code[1] : null,
        recurring: !!e.recurringEventId,
        status: eu ? eu.responseStatus : 'accepted',  // sem convidados = evento meu
        free: e.transparency === 'transparent',
        guests: (e.attendees || []).length,  // 0 ou 1 = bloco pessoal, não é reunião
      });
    });
    pageToken = r.nextPageToken;
  } while (pageToken);

  const json = JSON.stringify({ exported: new Date().toISOString(), events: eventos });
  const files = DriveApp.getFilesByName(ARQUIVO);
  if (files.hasNext()) files.next().setContent(json);
  else DriveApp.createFile(ARQUIVO, json, 'application/json');
}
