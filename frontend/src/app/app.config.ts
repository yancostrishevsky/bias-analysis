import { ApplicationConfig } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { provideRouter, withInMemoryScrolling } from '@angular/router';

import { API_BASE_URL } from './core/api/api.config';
import { getApiBaseUrl } from './core/api/runtime-config';
import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideHttpClient(),
    provideRouter(
      routes,
      withInMemoryScrolling({
        anchorScrolling: 'enabled'
      }),
    ),
    { provide: API_BASE_URL, useValue: getApiBaseUrl() }
  ]
};
