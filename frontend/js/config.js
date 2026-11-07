// Единственное место, которое меняется при переносе (локально / сервер / Dynamics 365 web resource).
export const CONFIG = {
  // true — всё работает на моках из ./mocks и localStorage, бэкенд не нужен.
  USE_MOCKS: false,
  // Same origin as the backend that serves this page: works on localhost:8000 and behind Cloudflare.
  API_BASE: '/api',
  // Набор по умолчанию для импорта от организаторов.
  DEFAULT_GROUP_ID: 'DEV',
};
