/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

const SESSION_COOKIE_NAME = 'session';
const TOKEN_QUERY_PARAM = 'token';

/**
 * When the app is opened with a `token` query parameter, persist it as the
 * session cookie and reload without the token in the URL so subsequent
 * requests authenticate without username/password login.
 *
 * @returns true when a redirect was triggered and the caller should stop booting.
 */
export default function setupTokenLogin(): boolean {
  if (typeof window === 'undefined') {
    return false;
  }

  const params = new URLSearchParams(window.location.search);
  const token = params.get(TOKEN_QUERY_PARAM);
  if (!token) {
    return false;
  }

  document.cookie = `${SESSION_COOKIE_NAME}=${token}; path=/dashboard/list/; SameSite=Lax`;

  params.delete(TOKEN_QUERY_PARAM);
  const remainingSearch = params.toString();
  const cleanUrl =
    window.location.pathname +
    (remainingSearch ? `?${remainingSearch}` : '') +
    window.location.hash;

  window.location.replace(cleanUrl);
  return true;
}
