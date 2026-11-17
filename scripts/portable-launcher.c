/* Tiny native launcher for a self-contained Python/Tk distribution. */
#ifdef _WIN32
#include <windows.h>
#include <process.h>
#include <wchar.h>
#include <stdlib.h>
/* The Windows CRT spawn family joins argv with spaces; quote for CommandLineToArgvW. */
static wchar_t *quote_arg(const wchar_t *input) {
    size_t length = wcslen(input);
    wchar_t *out = calloc(length * 2 + 3, sizeof(*out));
    if (!out) return NULL;
    wchar_t *p = out; *p++ = L'"';
    while (*input) {
        size_t slashes = 0;
        while (*input == L'\\') { ++slashes; ++input; }
        size_t count = (*input == L'"' || !*input) ? slashes * 2 : slashes;
        while (count--) *p++ = L'\\';
        if (!*input) break;
        if (*input == L'"') *p++ = L'\\';
        *p++ = *input++;
    }
    *p++ = L'"'; *p = 0;
    return out;
}
int wmain(int argc, wchar_t **argv) {
    wchar_t root[32768], python[32768], script[32768];
    DWORD n = GetModuleFileNameW(NULL, root, 32768);
    if (!n || n >= 32768) return 1;
    wchar_t *slash = wcsrchr(root, L'\\');
    if (!slash) return 1;
    *slash = 0;
    if (swprintf(python, 32768, L"%ls\\python\\python.exe", root) < 0 ||
        swprintf(script, 32768, L"%ls\\MobiPEG_Studio_V15.py", root) < 0) return 1;
    wchar_t **args = calloc(argc + 3, sizeof(*args));
    if (!args) return 1;
    args[0] = quote_arg(python); args[1] = quote_arg(L"-I"); args[2] = quote_arg(script);
    for (int i = 1; i < argc; ++i) args[i + 2] = quote_arg(argv[i]);
    for (int i = 0; i < argc + 2; ++i) if (!args[i]) return 1;
    intptr_t result = _wspawnv(_P_WAIT, python, (const wchar_t *const *)args);
    for (int i = 0; i < argc + 2; ++i) free(args[i]);
    free(args);
    return result < 0 ? 1 : (int)result;
}
#else
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
extern int _NSGetExecutablePath(char *, uint32_t *);
int main(int argc, char **argv) {
    char image[4096], real[4096], python[4096], script[4096];
    uint32_t size = sizeof(image);
    if (_NSGetExecutablePath(image, &size) || !realpath(image, real)) return 1;
    char *slash = strrchr(real, '/');
    if (!slash) return 1;
    *slash = 0;
    if (snprintf(python, sizeof(python), "%s/python/bin/python3", real) >= sizeof(python) ||
        snprintf(script, sizeof(script), "%s/MobiPEG_Studio_V15.py", real) >= sizeof(script)) return 1;
    char **args = calloc(argc + 3, sizeof(*args));
    if (!args) return 1;
    args[0] = python; args[1] = "-I"; args[2] = script;
    for (int i = 1; i < argc; ++i) args[i + 2] = argv[i];
    execv(python, args);
    perror("Cannot launch bundled Python");
    return 1;
}
#endif
