import { ApplicationConfig } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { provideRouter } from '@angular/router';

import { API_BASE_URL } from './core/api/api.config';
import { getApiBaseUrl } from './core/api/runtime-config';
import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideHttpClient(),
    provideRouter(routes),
    { provide: API_BASE_URL, useValue: getApiBaseUrl() }
  ]
};
